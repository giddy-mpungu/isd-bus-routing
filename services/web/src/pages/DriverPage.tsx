import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  AbsenceReason,
  Announcement,
  AssignmentStatus,
  DriverAssignment,
  DriverDispatchTask,
  DriverFieldTrip,
  DriverReportType,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { FINISHED, NEXT_STEP, STATUS_LABELS, STATUS_TONES } from '../assignmentStatus'
import { Badge, type BadgeTone } from '../components/Badge'
import { TASK_KIND_LABELS } from '../dispatchTasks'
import { buildDay, isUnderway, SLOT_LABELS, type QueueSlot } from '../driverDay'
import { nextMoving, speedAt, type Fix } from '../motion'

const ABSENCE_REASONS: AbsenceReason[] = [
  'sick_leave',
  'personal_day',
  'vacation',
  'emergency_leave',
  'training',
  'approved_leave',
  'administrative_direction',
  'injury',
  'no_call_no_show',
  'other',
]

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
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text))
}

function speakAssignment(a: DriverAssignment) {
  speak(
    `${a.school_name}, ${formatMinuteOfDay(a.start_minute)} to ${formatMinuteOfDay(a.end_minute)}, vehicle ${a.vehicle_label}.`,
  )
}

function speakTask(t: DriverDispatchTask) {
  speak(
    `${TASK_KIND_LABELS[t.kind]}, ${formatMinuteOfDay(t.start_minute)} to ${formatMinuteOfDay(t.end_minute)}` +
      `${t.location ? `, at ${t.location}` : ''}. ${t.instructions}`,
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
  return (
    <div className="driver-queue-slot">
      <Badge tone={SLOT_TONES[slot]}>{SLOT_LABELS[slot]}</Badge>
    </div>
  )
}

// A task's last two steps read better as "Start task" / "Task done".
function taskStepLabel(to: AssignmentStatus, label: string): string {
  if (to === 'in_progress') return 'Start task'
  if (to === 'completed') return 'Task done'
  return label
}

export function DriverPage() {
  const { user } = useAuth()
  const [serviceDate] = useState(today)
  const [assignments, setAssignments] = useState<DriverAssignment[]>([])
  const [tasks, setTasks] = useState<DriverDispatchTask[]>([])
  const [trips, setTrips] = useState<DriverFieldTrip[]>([])
  const [hasLoaded, setHasLoaded] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  // "run-12" / "task-3": the card whose button is waiting on the server.
  const [busyKey, setBusyKey] = useState<string | null>(null)
  // spec section 9: "Messages from dispatch" -- dispatcher-authored,
  // never auto-generated (see routers/announcements.py).
  const [announcements, setAnnouncements] = useState<Announcement[]>([])

  const loadDay = useCallback(async (date: string) => {
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
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to load your day.')
    } finally {
      setHasLoaded(true)
    }
  }, [])

  useEffect(() => {
    void loadDay(serviceDate)
  }, [serviceDate, loadDay])

  const day = buildDay(assignments, tasks, trips)
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
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to update run status.')
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
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to update the task.')
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
      setAbsenceError('Your account is not linked to a driver record.')
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
      setAbsenceError(err instanceof ApiError ? err.message : 'Failed to report absence.')
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
      setReportError('Your account is not linked to a driver record.')
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
      setReportError(err instanceof ApiError ? err.message : 'Failed to submit report.')
    } finally {
      setIsSavingReport(false)
    }
  }

  return (
    <div className="driver-page">
      <h1>My day — {serviceDate}</h1>

      {locked && (
        <p role="status" className="motion-lock">
          Bus moving: typing is locked until you stop. The next-step buttons still work.
        </p>
      )}

      {announcements.length > 0 && (
        <section className="announcements-panel">
          <h2>Messages from dispatch</h2>
          <ul>
            {announcements.map((a) => (
              <li key={a.id}>
                [{a.category.replace(/_/g, ' ')}] {a.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      {errorMessage && (
        <p role="alert" className="error">
          {errorMessage}
        </p>
      )}
      {hasLoaded && day.length === 0 && !errorMessage && (
        <p className="status">Nothing scheduled for you today.</p>
      )}

      <ul className="driver-run-list">
        {day.map(({ item, slot }) => {
          if (item.type === 'task') {
            const t = item.task
            const step = t.cancelled ? undefined : NEXT_STEP[t.status]
            return (
              <li
                key={item.key}
                className={`driver-run-card driver-task-card${t.cancelled ? ' is-cancelled' : ''}`}
              >
                <SlotLabel slot={slot} />
                <div className="driver-run-time">
                  {formatMinuteOfDay(t.start_minute)} – {formatMinuteOfDay(t.end_minute)}
                </div>
                <div className="driver-run-school">Dispatch: {TASK_KIND_LABELS[t.kind]}</div>
                {t.location && <div className="driver-run-vehicle">Where: {t.location}</div>}
                {t.vehicle_label && (
                  <div className="driver-run-vehicle">Vehicle: {t.vehicle_label}</div>
                )}
                <p className="driver-task-instructions">{t.instructions}</p>
                <div className="driver-run-status">
                  Status:{' '}
                  {t.cancelled ? (
                    <Badge tone="danger">Cancelled by dispatch</Badge>
                  ) : (
                    <Badge tone={STATUS_TONES[t.status]}>{STATUS_LABELS[t.status]}</Badge>
                  )}
                </div>
                <div className="driver-run-actions">
                  {step && (
                    <button
                      type="button"
                      className="driver-next-step"
                      disabled={busyKey === item.key}
                      onClick={() => void handleSetTaskStatus(t.id, step.to)}
                    >
                      {taskStepLabel(step.to, step.label)}
                    </button>
                  )}
                  <button type="button" onClick={() => speakTask(t)} aria-label="Read task aloud">
                    🔊 Read aloud
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
                  Field trip #{trip.id} to {trip.destination}
                </div>
                <div className="driver-run-vehicle">
                  Departs {formatTimestamp(trip.departure_at)} from {trip.origin}, returns{' '}
                  {formatTimestamp(trip.return_at)}
                </div>
                {trip.vehicle_label && (
                  <div className="driver-run-vehicle">Vehicle: {trip.vehicle_label}</div>
                )}
                <div className="driver-run-vehicle">
                  {trip.passenger_count} passengers for {trip.requesting_party}. Contact:{' '}
                  {trip.trip_contact}
                  {trip.bus_assistant_name && `. Bus assistant: ${trip.bus_assistant_name}`}
                </div>
                {trip.special_instructions && (
                  <p className="driver-task-instructions">{trip.special_instructions}</p>
                )}
                {profile && (
                  <ul className="driver-trip-notes">
                    {profile.approved_entrance && (
                      <li>Approved entrance: {profile.approved_entrance}</li>
                    )}
                    {profile.parking_notes && <li>Parking: {profile.parking_notes}</li>}
                    {profile.turn_restrictions && (
                      <li>Turn restrictions: {profile.turn_restrictions}</li>
                    )}
                    {profile.driver_notes && <li>Driver notes: {profile.driver_notes}</li>}
                  </ul>
                )}
                <div className="driver-run-status">
                  Trip status:{' '}
                  <Badge tone={trip.status === 'completed' ? 'success' : 'info'}>
                    {trip.status.replace(/_/g, ' ')}
                  </Badge>
                </div>
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
              <div className="driver-run-vehicle">Vehicle: {a.vehicle_label}</div>
              <div className="driver-run-status">
                Status: <Badge tone={STATUS_TONES[a.status]}>{STATUS_LABELS[a.status]}</Badge>
              </div>
              <div className="driver-run-roster">
                {a.roster_ambiguous ? (
                  <p>
                    Rider list unavailable — more than one bus serves this school today, so it can't
                    be split between them.
                  </p>
                ) : a.stops.length === 0 ? (
                  <p>No riders expected today.</p>
                ) : a.stops_ordered ? (
                  <>
                    <h3>Stops in order</h3>
                    <ol className="driver-route-stops">
                      {a.stops
                        .filter((stop) => stop.on_route !== false)
                        .map((stop) => (
                          <li key={`${stop.position}-${stop.stop_label}`}>
                            {stop.planned_minute != null && (
                              <>
                                <span className="driver-stop-time">
                                  {formatMinuteOfDay(stop.planned_minute)}
                                </span>{' '}
                              </>
                            )}
                            <strong>{stop.stop_label}</strong>
                            {': '}
                            {stop.student_names.length > 0
                              ? stop.student_names.join(', ')
                              : 'nobody expected today'}
                          </li>
                        ))}
                    </ol>
                    {a.stops.some((stop) => stop.on_route === false) && (
                      <>
                        <p className="driver-run-roster-note">
                          Also expected, at stops not on this route:
                        </p>
                        <ul>
                          {a.stops
                            .filter((stop) => stop.on_route === false)
                            .map((stop) => (
                              <li key={`off-${stop.stop_label ?? '__no_stop__'}`}>
                                {stop.stop_label ?? 'No stop assigned'}:{' '}
                                {stop.student_names.join(', ')}
                              </li>
                            ))}
                        </ul>
                      </>
                    )}
                  </>
                ) : (
                  <>
                    <h3>Expected riders by stop</h3>
                    <p className="driver-run-roster-note">
                      Not a route order: this run's route has no stop list yet.
                    </p>
                    <ul>
                      {a.stops.map((stop) => (
                        <li key={stop.stop_label ?? '__no_stop__'}>
                          {stop.stop_label ?? 'No stop assigned'}: {stop.student_names.join(', ')}
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
                    disabled={busyKey === item.key}
                    onClick={() => void handleSetStatus(a.id, NEXT_STEP[a.status]!.to)}
                  >
                    {NEXT_STEP[a.status]!.label}
                  </button>
                )}
                {!FINISHED.includes(a.status) && (
                  <button
                    type="button"
                    className="btn-danger"
                    disabled={busyKey === item.key || locked}
                    title={locked ? 'Stop the bus first' : undefined}
                    onClick={() => void handleSetStatus(a.id, 'no_show')}
                  >
                    No-show
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => speakAssignment(a)}
                  aria-label="Read run aloud"
                >
                  🔊 Read aloud
                </button>
              </div>
            </li>
          )
        })}
      </ul>

      <section className="driver-absence-section">
        <h2>Report an absence</h2>
        <form onSubmit={(event) => void handleReportAbsence(event)}>
          <fieldset className="motion-lockable" disabled={locked}>
            <label htmlFor="driver-absence-reason">Reason</label>
            <select
              id="driver-absence-reason"
              value={absenceReason}
              onChange={(event) => setAbsenceReason(event.target.value as AbsenceReason)}
            >
              {ABSENCE_REASONS.map((reason) => (
                <option key={reason} value={reason}>
                  {reason.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={absenceWholeDay}
                onChange={(event) => setAbsenceWholeDay(event.target.checked)}
              />
              Whole day
            </label>
            {!absenceWholeDay && (
              <>
                <label htmlFor="driver-absence-start">Start (minute of day)</label>
                <input
                  id="driver-absence-start"
                  type="number"
                  min="0"
                  max="1439"
                  value={absenceStartMinute}
                  onChange={(event) => setAbsenceStartMinute(event.target.value)}
                  required
                />
                <label htmlFor="driver-absence-end">End (minute of day)</label>
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
            {absenceSuccess && <p className="status">Absence reported.</p>}
            <button type="submit" disabled={isSavingAbsence}>
              {isSavingAbsence ? 'Reporting…' : 'Report absence'}
            </button>
          </fieldset>
        </form>
      </section>

      <section className="driver-report-section">
        <h2>Report an incident or vehicle defect</h2>
        <form onSubmit={(event) => void handleSubmitReport(event)}>
          <fieldset className="motion-lockable" disabled={locked}>
            <label htmlFor="driver-report-type">Type</label>
            <select
              id="driver-report-type"
              value={reportType}
              onChange={(event) => setReportType(event.target.value as DriverReportType)}
            >
              <option value="incident">Incident</option>
              <option value="vehicle_defect">Vehicle defect</option>
            </select>
            <label htmlFor="driver-report-description">Description</label>
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
            {reportSuccess && <p className="status">Report submitted.</p>}
            <button type="submit" disabled={isSavingReport}>
              {isSavingReport ? 'Submitting…' : 'Submit report'}
            </button>
          </fieldset>
        </form>
      </section>
    </div>
  )
}
