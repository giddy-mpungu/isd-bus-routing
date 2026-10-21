import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { savedDay, saveDay } from '../offlineDay'
import { ApiError } from '../api/client'
import type {
  AbsenceReason,
  Announcement,
  AssignmentStatus,
  DriverAssignment,
  DriverDispatchTask,
  DriverFieldTrip,
  DriverReportType,
  TripStatus,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { FINISHED, NEXT_STEP, STATUS_LABELS, STATUS_TONES } from '../assignmentStatus'
import { Badge, type BadgeTone } from '../components/Badge'
import { TASK_KIND_LABELS } from '../dispatchTasks'
import { buildDay, isUnderway, SLOT_LABELS, type QueueSlot } from '../driverDay'
import {
  currentLanguage,
  LOCALES,
  translateNow as tNow,
  useTranslation,
  type Phrase,
} from '../i18n'
import { DirectionsPanel } from './DirectionsPanel'
import { nextMoving, speedAt, type Fix } from '../motion'

const ABSENCE_REASONS: Record<AbsenceReason, Phrase> = {
  sick_leave: 'sick leave',
  personal_day: 'personal day',
  vacation: 'vacation',
  emergency_leave: 'emergency leave',
  training: 'training',
  approved_leave: 'approved leave',
  administrative_direction: 'administrative direction',
  injury: 'injury',
  no_call_no_show: 'no call, no show',
  other: 'other',
}

const TRIP_STATUSES: Record<TripStatus, Phrase> = {
  requested: 'requested',
  approved: 'approved',
  assigned: 'assigned',
  dispatched: 'dispatched',
  in_progress: 'in progress',
  returning: 'returning',
  completed: 'completed',
}

// The announcement's text is written by staff and shown as written.
const CATEGORIES: Record<Announcement['category'], Phrase> = {
  general: 'general',
  delay: 'delay',
  substitution: 'substitution',
  route_change: 'route change',
}

// How often the moving tablet sends its position to dispatch.
const REPORT_EVERY_MS = 20_000

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatMinuteOfDay(minute: number): string {
  const hours = Math.floor(minute / 60)
  const mins = minute % 60
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`
}

function speak(text: string) {
  // Spec section 9: "audible instructions" for drivers. Native browser
  // API, zero dependencies — a no-op where unsupported (older
  // browsers, some in-vehicle tablets) rather than an error.
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    return
  }
  const utterance = new SpeechSynthesisUtterance(text)
  // In the screen's language, so a Spanish voice reads Spanish.
  utterance.lang = LOCALES[currentLanguage()]
  window.speechSynthesis.speak(utterance)
}

function speakAssignment(a: DriverAssignment) {
  speak(
    tNow('{school}, {start} to {end}, vehicle {vehicle}.', {
      school: a.school_name,
      start: formatMinuteOfDay(a.start_minute),
      end: formatMinuteOfDay(a.end_minute),
      vehicle: a.vehicle_label,
    }),
  )
}

function speakTask(task: DriverDispatchTask) {
  const when = {
    kind: tNow(TASK_KIND_LABELS[task.kind]),
    start: formatMinuteOfDay(task.start_minute),
    end: formatMinuteOfDay(task.end_minute),
  }
  speak(
    (task.location
      ? tNow('{kind}, {start} to {end}, at {place}.', { ...when, place: task.location })
      : tNow('{kind}, {start} to {end}.', when)) + ` ${task.instructions}`,
  )
}

// "2026-10-08T09:00:00" -> "2026-10-08 09:00"
function formatTimestamp(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}

const SLOT_TONES: Record<QueueSlot, BadgeTone> = {
  current: 'info',
  next: 'neutral',
  later: 'neutral',
  done: 'success',
  cancelled: 'danger',
}

function SlotLabel({ slot }: { slot: QueueSlot }) {
  const { t } = useTranslation()
  return (
    <div className="driver-queue-slot">
      <Badge tone={SLOT_TONES[slot]}>{t(SLOT_LABELS[slot])}</Badge>
    </div>
  )
}

// A task's last two steps read better as "Start task" / "Task done".
function taskStepLabel(to: AssignmentStatus, label: Phrase): Phrase {
  if (to === 'in_progress') return 'Start task'
  if (to === 'completed') return 'Task done'
  return label
}

export function DriverPage() {
  const { user } = useAuth()
  const { t } = useTranslation()
  const [serviceDate] = useState(today)
  const [assignments, setAssignments] = useState<DriverAssignment[]>([])
  const [tasks, setTasks] = useState<DriverDispatchTask[]>([])
  const [trips, setTrips] = useState<DriverFieldTrip[]>([])
  const [hasLoaded, setHasLoaded] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  // When the tablet has no signal: the time of the saved copy on screen.
  const [noSignal, setNoSignal] = useState(false)
  // "run-12" / "task-3": the card whose button is waiting on the server.
  const [busyKey, setBusyKey] = useState<string | null>(null)
  // spec section 9: "Messages from dispatch" -- dispatcher-authored,
  // never auto-generated (see routers/announcements.py).
  const [announcements, setAnnouncements] = useState<Announcement[]>([])

  const loadDay = useCallback(
    async (date: string) => {
      setErrorMessage(null)
      try {
        const [myRuns, myTasks, myTrips] = await Promise.all([
          api.getMyAssignments(date),
          api.getMyDispatchTasks(date),
          api.getMyFieldTrips(date),
        ])
        // Spec section 14: tell dispatch the tablet has received new work.
        const [runs, tasksNow] = await Promise.all([
          myRuns.some((a) => a.status === 'sent') ? api.markAssignmentsReceived(date) : myRuns,
          myTasks.some((t) => t.status === 'sent' && !t.cancelled)
            ? api.markDispatchTasksReceived(date)
            : myTasks,
        ])
        setAssignments(runs)
        setTasks(tasksNow)
        setTrips(myTrips)
        setNoSignal(false)
      } catch (err) {
        if (err instanceof ApiError) {
          setErrorMessage(err.message)
        } else {
          // No answer at all: no signal. The saved day is shown below.
          setNoSignal(true)
        }
      } finally {
        setHasLoaded(true)
      }
    },
    [t],
  )

  // Spec section 19: keep the day as loaded, for this driver and date only.
  useEffect(() => {
    if (user && hasLoaded && !noSignal) {
      saveDay(user.id, serviceDate, { assignments, tasks, trips })
    }
  }, [user, hasLoaded, noSignal, serviceDate, assignments, tasks, trips])

  // Back in signal: load the day again.
  useEffect(() => {
    const reload = () => void loadDay(serviceDate)
    window.addEventListener('online', reload)
    return () => window.removeEventListener('online', reload)
  }, [loadDay, serviceDate])

  useEffect(() => {
    void loadDay(serviceDate)
  }, [serviceDate, loadDay])

  // No signal: the day as last loaded, read-only, if there is one.
  const saved = noSignal && user ? savedDay(user.id, serviceDate) : null
  const offlineSince = saved?.savedAt ?? null
  const day = saved
    ? buildDay(saved.assignments, saved.tasks, saved.trips)
    : buildDay(assignments, tasks, trips)
  const shownError =
    errorMessage ?? (noSignal && user && !saved ? t('Failed to load your day.') : null)
  const anythingUnderway = day.some(({ item }) => isUnderway(item))

  useEffect(() => {
    api
      .getMyAnnouncements()
      .then(setAnnouncements)
      .catch(() => undefined)
  }, [])

  // ADR 0009: one continuous GPS feed while work is under way does two
  // jobs, with no driver interaction (spec section 9: "limited driver
  // interaction while moving"): it reports the bus's position to dispatch
  // at most every REPORT_EVERY_MS, and tells whether the bus is moving
  // (motion.ts), which locks typing. Silently does nothing if the browser
  // has no geolocation, permission was denied, or this login isn't linked
  // to a driver record: a best-effort aid, never something that blocks or
  // alarms a driver just trying to run their route.
  const [isMoving, setIsMoving] = useState(false)
  useEffect(() => {
    const driverId = user?.driver_id
    if (driverId == null || !anythingUnderway || !('geolocation' in navigator)) {
      return
    }
    let previous: Fix | null = null
    let moving = false
    let lastReportedAt = Number.NEGATIVE_INFINITY
    // Stopped on the same object it started on.
    const geolocation = navigator.geolocation
    const watchId = geolocation.watchPosition(
      (position) => {
        const fix: Fix = {
          lat: position.coords.latitude,
          lon: position.coords.longitude,
          time: position.timestamp,
          speed: position.coords.speed ?? null,
        }
        moving = nextMoving(moving, speedAt(previous, fix))
        previous = fix
        setIsMoving(moving)
        if (fix.time - lastReportedAt >= REPORT_EVERY_MS) {
          lastReportedAt = fix.time
          void api
            .reportPosition(driverId, {
              service_date: serviceDate,
              location_lat: fix.lat,
              location_lon: fix.lon,
              recorded_at: new Date(fix.time).toISOString(),
            })
            .catch(() => undefined)
        }
      },
      // Lost or refused GPS can't prove the bus is moving.
      () => {
        moving = false
        setIsMoving(false)
      },
      { enableHighAccuracy: true, maximumAge: 5000 },
    )
    return () => geolocation.clearWatch(watchId)
  }, [anythingUnderway, user, serviceDate])
  // Only while something is under way: once the run ends, nothing is locked.
  const locked = anythingUnderway && isMoving

  async function handleSetStatus(assignmentId: number, status: AssignmentStatus) {
    setErrorMessage(null)
    setBusyKey(`run-${assignmentId}`)
    try {
      await api.updateAssignmentStatus(assignmentId, status)
      await loadDay(serviceDate)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : t('Failed to update run status.'))
    } finally {
      setBusyKey(null)
    }
  }

  async function handleSetTaskStatus(taskId: number, status: AssignmentStatus) {
    setErrorMessage(null)
    setBusyKey(`task-${taskId}`)
    try {
      await api.updateDispatchTaskStatus(taskId, status)
      await loadDay(serviceDate)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : t('Failed to update the task.'))
    } finally {
      setBusyKey(null)
    }
  }

  // --- Report my own absence (spec section 13: a driver can report
  // their own absence; POST /drivers/{id}/absences already supports
  // this — the API only needed a button, per REBOOT.md's own note). ---
  const [absenceReason, setAbsenceReason] = useState<AbsenceReason>('sick_leave')
  const [absenceWholeDay, setAbsenceWholeDay] = useState(true)
  const [absenceStartMinute, setAbsenceStartMinute] = useState('0')
  const [absenceEndMinute, setAbsenceEndMinute] = useState('1439')
  const [absenceError, setAbsenceError] = useState<string | null>(null)
  const [absenceSuccess, setAbsenceSuccess] = useState(false)
  const [isSavingAbsence, setIsSavingAbsence] = useState(false)

  async function handleReportAbsence(event: FormEvent) {
    event.preventDefault()
    setAbsenceError(null)
    setAbsenceSuccess(false)
    if (user?.driver_id == null) {
      setAbsenceError(t('Your account is not linked to a driver record.'))
      return
    }
    setIsSavingAbsence(true)
    try {
      await api.createAbsence(user.driver_id, {
        service_date: serviceDate,
        start_minute: absenceWholeDay ? 0 : Number(absenceStartMinute),
        end_minute: absenceWholeDay ? 1439 : Number(absenceEndMinute),
        reason: absenceReason,
      })
      setAbsenceReason('sick_leave')
      setAbsenceWholeDay(true)
      setAbsenceStartMinute('0')
      setAbsenceEndMinute('1439')
      setAbsenceSuccess(true)
    } catch (err) {
      setAbsenceError(err instanceof ApiError ? err.message : t('Failed to report absence.'))
    } finally {
      setIsSavingAbsence(false)
    }
  }

  // --- Report an incident / vehicle defect (spec section 9) ---
  const [reportType, setReportType] = useState<DriverReportType>('incident')
  const [reportDescription, setReportDescription] = useState('')
  const [reportError, setReportError] = useState<string | null>(null)
  const [reportSuccess, setReportSuccess] = useState(false)
  const [isSavingReport, setIsSavingReport] = useState(false)

  async function handleSubmitReport(event: FormEvent) {
    event.preventDefault()
    setReportError(null)
    setReportSuccess(false)
    if (user?.driver_id == null) {
      setReportError(t('Your account is not linked to a driver record.'))
      return
    }
    setIsSavingReport(true)
    try {
      await api.createDriverReport(user.driver_id, {
        service_date: serviceDate,
        report_type: reportType,
        description: reportDescription,
      })
      setReportType('incident')
      setReportDescription('')
      setReportSuccess(true)
    } catch (err) {
      setReportError(err instanceof ApiError ? err.message : t('Failed to submit report.'))
    } finally {
      setIsSavingReport(false)
    }
  }

  return (
    <div className="driver-page">
      <h1>{t('My day — {date}', { date: serviceDate })}</h1>

      {locked && (
        <p role="status" className="motion-lock">
          {t('Bus moving: typing is locked until you stop. The next-step buttons still work.')}
        </p>
      )}

      {announcements.length > 0 && (
        <section className="announcements-panel">
          <h2>{t('Messages from dispatch')}</h2>
          <ul>
            {announcements.map((a) => (
              <li key={a.id}>
                [{t(CATEGORIES[a.category])}] {a.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      {offlineSince && (
        <p role="status" className="driver-offline">
          {t("No signal. This is your day as of {time}. Buttons work again when there's signal.", {
            time: new Date(offlineSince).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            }),
          })}{' '}
          <button type="button" onClick={() => void loadDay(serviceDate)}>
            {t('Try again')}
          </button>
        </p>
      )}
      {shownError && (
        <p role="alert" className="error">
          {shownError}
        </p>
      )}
      {hasLoaded && day.length === 0 && !shownError && (
        <p className="status">{t('Nothing scheduled for you today.')}</p>
      )}

      <ul className="driver-run-list">
        {day.map(({ item, slot }) => {
          if (item.type === 'task') {
            const task = item.task
            const step = task.cancelled ? undefined : NEXT_STEP[task.status]
            return (
              <li
                key={item.key}
                className={`driver-run-card driver-task-card${task.cancelled ? ' is-cancelled' : ''}`}
              >
                <SlotLabel slot={slot} />
                <div className="driver-run-time">
                  {formatMinuteOfDay(task.start_minute)} – {formatMinuteOfDay(task.end_minute)}
                </div>
                <div className="driver-run-school">
                  {t('Dispatch: {kind}', { kind: t(TASK_KIND_LABELS[task.kind]) })}
                </div>
                {task.location && (
                  <div className="driver-run-vehicle">
                    {t('Where: {place}', { place: task.location })}
                  </div>
                )}
                {task.vehicle_label && (
                  <div className="driver-run-vehicle">
                    {t('Vehicle: {vehicle}', { vehicle: task.vehicle_label })}
                  </div>
                )}
                <p className="driver-task-instructions">{task.instructions}</p>
                <div className="driver-run-status">
                  {t('Status:')}{' '}
                  {task.cancelled ? (
                    <Badge tone="danger">{t('Cancelled by dispatch')}</Badge>
                  ) : (
                    <Badge tone={STATUS_TONES[task.status]}>{t(STATUS_LABELS[task.status])}</Badge>
                  )}
                </div>
                <div className="driver-run-actions">
                  {step && (
                    <button
                      type="button"
                      className="driver-next-step"
                      disabled={busyKey === item.key || offlineSince !== null}
                      onClick={() => void handleSetTaskStatus(task.id, step.to)}
                    >
                      {t(taskStepLabel(step.to, step.label))}
                    </button>
                  )}
                  <button type="button" onClick={() => speakTask(task)}>
                    <span aria-hidden="true">🔊</span> {t('Read aloud')}
                  </button>
                </div>
              </li>
            )
          }
          if (item.type === 'trip') {
            const trip = item.trip
            const profile = trip.destination_profile
            return (
              <li key={item.key} className="driver-run-card driver-trip-card">
                <SlotLabel slot={slot} />
                <div className="driver-run-time">
                  {formatMinuteOfDay(trip.start_minute)} – {formatMinuteOfDay(trip.end_minute)}
                </div>
                <div className="driver-run-school">
                  {t('Field trip #{id} to {destination}', {
                    id: trip.id,
                    destination: trip.destination,
                  })}
                </div>
                <div className="driver-run-vehicle">
                  {t('Departs {departs} from {origin}, returns {returns}', {
                    departs: formatTimestamp(trip.departure_at),
                    origin: trip.origin,
                    returns: formatTimestamp(trip.return_at),
                  })}
                </div>
                {trip.vehicle_label && (
                  <div className="driver-run-vehicle">
                    {t('Vehicle: {vehicle}', { vehicle: trip.vehicle_label })}
                  </div>
                )}
                <div className="driver-run-vehicle">
                  {t('{count} passengers for {party}. Contact: {contact}', {
                    count: trip.passenger_count,
                    party: trip.requesting_party,
                    contact: trip.trip_contact,
                  })}
                  {trip.bus_assistant_name &&
                    t('. Bus assistant: {name}', { name: trip.bus_assistant_name })}
                </div>
                {trip.special_instructions && (
                  <p className="driver-task-instructions">{trip.special_instructions}</p>
                )}
                {profile && (
                  <ul className="driver-trip-notes">
                    {profile.approved_entrance && (
                      <li>{t('Approved entrance: {text}', { text: profile.approved_entrance })}</li>
                    )}
                    {profile.parking_notes && (
                      <li>{t('Parking: {text}', { text: profile.parking_notes })}</li>
                    )}
                    {profile.turn_restrictions && (
                      <li>{t('Turn restrictions: {text}', { text: profile.turn_restrictions })}</li>
                    )}
                    {profile.driver_notes && (
                      <li>{t('Driver notes: {text}', { text: profile.driver_notes })}</li>
                    )}
                  </ul>
                )}
                <div className="driver-run-status">
                  {t('Trip status:')}{' '}
                  <Badge tone={trip.status === 'completed' ? 'success' : 'info'}>
                    {t(TRIP_STATUSES[trip.status])}
                  </Badge>
                </div>
                <DirectionsPanel tripId={trip.id} />
              </li>
            )
          }
          const a = item.run
          return (
            <li key={item.key} className="driver-run-card">
              <SlotLabel slot={slot} />
              <div className="driver-run-time">
                {formatMinuteOfDay(a.start_minute)} – {formatMinuteOfDay(a.end_minute)}
              </div>
              <div className="driver-run-school">{a.school_name}</div>
              <div className="driver-run-vehicle">
                {t('Vehicle: {vehicle}', { vehicle: a.vehicle_label })}
              </div>
              <div className="driver-run-status">
                {t('Status:')}{' '}
                <Badge tone={STATUS_TONES[a.status]}>{t(STATUS_LABELS[a.status])}</Badge>
              </div>
              <div className="driver-run-roster">
                {a.roster_ambiguous ? (
                  <p>
                    {t(
                      "Rider list unavailable — more than one bus serves this school today, so it can't be split between them.",
                    )}
                  </p>
                ) : a.stops.length === 0 ? (
                  <p>{t('No riders expected today.')}</p>
                ) : a.stops_ordered ? (
                  <>
                    <h3>{t('Stops in order')}</h3>
                    <ol className="driver-route-stops">
                      {a.stops
                        .filter((stop) => stop.on_route !== false)
                        .map((stop) => (
                          <li
                            key={`${stop.position}-${stop.stop_label}`}
                            className={stop.skipped ? 'is-skipped' : undefined}
                          >
                            {!stop.skipped && (stop.eta_minute ?? stop.planned_minute) != null && (
                              <>
                                <span className="driver-stop-time">
                                  {formatMinuteOfDay((stop.eta_minute ?? stop.planned_minute)!)}
                                </span>{' '}
                              </>
                            )}
                            <strong>{stop.stop_label}</strong>
                            {': '}
                            {stop.skipped
                              ? t('skip, nobody riding today')
                              : stop.student_names.length > 0
                                ? stop.student_names.join(', ')
                                : t('nobody expected today')}
                            {stop.eta_minute != null &&
                              stop.planned_minute != null &&
                              stop.eta_minute !== stop.planned_minute && (
                                <span className="driver-stop-planned">
                                  {' '}
                                  {t('(planned {time})', {
                                    time: formatMinuteOfDay(stop.planned_minute),
                                  })}
                                </span>
                              )}
                          </li>
                        ))}
                    </ol>
                    {(a.closure_notes ?? []).length > 0 && (
                      <div className="driver-closure" role="status">
                        <strong>{t('Road closure near your route.')}</strong>{' '}
                        {t('Directions go around it.')}
                        <ul>
                          {(a.closure_notes ?? []).map((n) => (
                            <li key={n}>{n}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <DirectionsPanel assignmentId={a.id} />
                    {a.stops.some((stop) => stop.on_route === false) && (
                      <>
                        <p className="driver-run-roster-note">
                          {t('Also expected, at stops not on this route:')}
                        </p>
                        <ul>
                          {a.stops
                            .filter((stop) => stop.on_route === false)
                            .map((stop) => (
                              <li key={`off-${stop.stop_label ?? '__no_stop__'}`}>
                                {stop.stop_label ?? t('No stop assigned')}:{' '}
                                {stop.student_names.join(', ')}
                              </li>
                            ))}
                        </ul>
                      </>
                    )}
                  </>
                ) : (
                  <>
                    <h3>{t('Expected riders by stop')}</h3>
                    <p className="driver-run-roster-note">
                      {t("Not a route order: this run's route has no stop list yet.")}
                    </p>
                    <ul>
                      {a.stops.map((stop) => (
                        <li key={stop.stop_label ?? '__no_stop__'}>
                          {stop.stop_label ?? t('No stop assigned')}:{' '}
                          {stop.student_names.join(', ')}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
              <div className="driver-run-actions">
                {NEXT_STEP[a.status] && (
                  <button
                    type="button"
                    className="driver-next-step"
                    disabled={busyKey === item.key || offlineSince !== null}
                    onClick={() => void handleSetStatus(a.id, NEXT_STEP[a.status]!.to)}
                  >
                    {t(NEXT_STEP[a.status]!.label)}
                  </button>
                )}
                {!FINISHED.includes(a.status) && (
                  <button
                    type="button"
                    className="btn-danger"
                    disabled={busyKey === item.key || locked || offlineSince !== null}
                    title={locked ? t('Stop the bus first') : undefined}
                    onClick={() => void handleSetStatus(a.id, 'no_show')}
                  >
                    {t('No-show')}
                  </button>
                )}
                <button type="button" onClick={() => speakAssignment(a)}>
                  {/* The name is the visible words (WCAG 2.5.3); the icon is decoration. */}
                  <span aria-hidden="true">🔊</span> {t('Read aloud')}
                </button>
              </div>
            </li>
          )
        })}
      </ul>

      <section className="driver-absence-section">
        <h2>{t('Report an absence')}</h2>
        <form onSubmit={(event) => void handleReportAbsence(event)}>
          <fieldset className="motion-lockable" disabled={locked}>
            <label htmlFor="driver-absence-reason">{t('Reason')}</label>
            <select
              id="driver-absence-reason"
              value={absenceReason}
              onChange={(event) => setAbsenceReason(event.target.value as AbsenceReason)}
            >
              {(Object.keys(ABSENCE_REASONS) as AbsenceReason[]).map((reason) => (
                <option key={reason} value={reason}>
                  {t(ABSENCE_REASONS[reason])}
                </option>
              ))}
            </select>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={absenceWholeDay}
                onChange={(event) => setAbsenceWholeDay(event.target.checked)}
              />
              {t('Whole day')}
            </label>
            {!absenceWholeDay && (
              <>
                <label htmlFor="driver-absence-start">{t('Start (minute of day)')}</label>
                <input
                  id="driver-absence-start"
                  type="number"
                  min="0"
                  max="1439"
                  value={absenceStartMinute}
                  onChange={(event) => setAbsenceStartMinute(event.target.value)}
                  required
                />
                <label htmlFor="driver-absence-end">{t('End (minute of day)')}</label>
                <input
                  id="driver-absence-end"
                  type="number"
                  min="0"
                  max="1439"
                  value={absenceEndMinute}
                  onChange={(event) => setAbsenceEndMinute(event.target.value)}
                  required
                />
              </>
            )}
            {absenceError && (
              <p role="alert" className="error">
                {absenceError}
              </p>
            )}
            {absenceSuccess && <p className="status">{t('Absence reported.')}</p>}
            <button type="submit" disabled={isSavingAbsence}>
              {isSavingAbsence ? t('Reporting…') : t('Report absence')}
            </button>
          </fieldset>
        </form>
      </section>

      <section className="driver-report-section">
        <h2>{t('Report an incident or vehicle defect')}</h2>
        <form onSubmit={(event) => void handleSubmitReport(event)}>
          <fieldset className="motion-lockable" disabled={locked}>
            <label htmlFor="driver-report-type">{t('Type')}</label>
            <select
              id="driver-report-type"
              value={reportType}
              onChange={(event) => setReportType(event.target.value as DriverReportType)}
            >
              <option value="incident">{t('Incident')}</option>
              <option value="vehicle_defect">{t('Vehicle defect')}</option>
            </select>
            <label htmlFor="driver-report-description">{t('Description')}</label>
            <textarea
              id="driver-report-description"
              value={reportDescription}
              onChange={(event) => setReportDescription(event.target.value)}
              required
            />
            {reportError && (
              <p role="alert" className="error">
                {reportError}
              </p>
            )}
            {reportSuccess && <p className="status">{t('Report submitted.')}</p>}
            <button type="submit" disabled={isSavingReport}>
              {isSavingReport ? t('Submitting…') : t('Submit report')}
            </button>
          </fieldset>
        </form>
      </section>
    </div>
  )
}
