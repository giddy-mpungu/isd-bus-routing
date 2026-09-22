import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  AbsenceReason,
  Announcement,
  AssignmentStatus,
  DriverAssignment,
  DriverReportType,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'

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

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatMinuteOfDay(minute: number): string {
  const hours = Math.floor(minute / 60)
  const mins = minute % 60
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`
}

const STATUS_LABELS: Record<AssignmentStatus, string> = {
  scheduled: 'Not started',
  in_progress: 'In progress',
  completed: 'Completed',
  no_show: 'No-show',
}

const STATUS_TONES: Record<AssignmentStatus, BadgeTone> = {
  scheduled: 'neutral',
  in_progress: 'info',
  completed: 'success',
  no_show: 'danger',
}

function speakAssignment(a: DriverAssignment) {
  // Spec section 9: "audible instructions" for drivers. Native browser
  // API, zero dependencies — a no-op where unsupported (older
  // browsers, some in-vehicle tablets) rather than an error.
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    return
  }
  const text = `${a.school_name}, ${formatMinuteOfDay(a.start_minute)} to ${formatMinuteOfDay(a.end_minute)}, vehicle ${a.vehicle_label}.`
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text))
}

export function DriverPage() {
  const { user } = useAuth()
  const [serviceDate] = useState(today)
  const [assignments, setAssignments] = useState<DriverAssignment[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [busyAssignmentId, setBusyAssignmentId] = useState<number | null>(null)
  // spec section 9: "Messages from dispatch" -- dispatcher-authored,
  // never auto-generated (see routers/announcements.py).
  const [announcements, setAnnouncements] = useState<Announcement[]>([])

  const loadAssignments = useCallback(async (date: string) => {
    setErrorMessage(null)
    try {
      setAssignments(await api.getMyAssignments(date))
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to load your runs.')
    }
  }, [])

  useEffect(() => {
    void loadAssignments(serviceDate)
  }, [serviceDate, loadAssignments])

  useEffect(() => {
    api
      .getMyAnnouncements()
      .then(setAnnouncements)
      .catch(() => undefined)
  }, [])

  // ADR 0009: report this vehicle's position periodically while a run
  // is actually in progress -- automatic, no driver interaction (spec
  // section 9: "limited driver interaction while moving"). Silently
  // does nothing if the browser has no geolocation, permission was
  // denied, or this login isn't linked to a driver record -- position
  // reporting is a best-effort enhancement, not something that should
  // block or alarm a driver just trying to run their route.
  useEffect(() => {
    const driverId = user?.driver_id
    const hasActiveAssignment = assignments.some((a) => a.status === 'in_progress')
    if (driverId == null || !hasActiveAssignment || !('geolocation' in navigator)) {
      return
    }
    const reportPosition = () => {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          void api
            .reportPosition(driverId, {
              service_date: serviceDate,
              location_lat: position.coords.latitude,
              location_lon: position.coords.longitude,
              recorded_at: new Date(position.timestamp).toISOString(),
            })
            .catch(() => undefined)
        },
        () => undefined,
      )
    }
    reportPosition()
    const intervalId = window.setInterval(reportPosition, 20000)
    return () => window.clearInterval(intervalId)
  }, [assignments, user, serviceDate])

  async function handleSetStatus(assignmentId: number, status: AssignmentStatus) {
    setErrorMessage(null)
    setBusyAssignmentId(assignmentId)
    try {
      await api.updateAssignmentStatus(assignmentId, status)
      await loadAssignments(serviceDate)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to update run status.')
    } finally {
      setBusyAssignmentId(null)
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
      <h1>My runs — {serviceDate}</h1>

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
      {assignments.length === 0 && !errorMessage && (
        <p className="status">No runs scheduled for today.</p>
      )}

      <ul className="driver-run-list">
        {assignments.map((a) => (
          <li key={a.id} className="driver-run-card">
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
              ) : (
                <>
                  <h3>Expected riders by stop</h3>
                  <p className="driver-run-roster-note">
                    Not a route order — stops aren't sequenced yet.
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
              <button
                type="button"
                disabled={a.status === 'in_progress' || busyAssignmentId === a.id}
                onClick={() => void handleSetStatus(a.id, 'in_progress')}
              >
                Start
              </button>
              <button
                type="button"
                disabled={a.status === 'completed' || busyAssignmentId === a.id}
                onClick={() => void handleSetStatus(a.id, 'completed')}
              >
                Complete
              </button>
              <button
                type="button"
                disabled={a.status === 'no_show' || busyAssignmentId === a.id}
                onClick={() => void handleSetStatus(a.id, 'no_show')}
              >
                No-show
              </button>
              <button type="button" onClick={() => speakAssignment(a)} aria-label="Read run aloud">
                🔊 Read aloud
              </button>
            </div>
          </li>
        ))}
      </ul>

      <section className="driver-absence-section">
        <h2>Report an absence</h2>
        <form onSubmit={(event) => void handleReportAbsence(event)}>
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
        </form>
      </section>

      <section className="driver-report-section">
        <h2>Report an incident or vehicle defect</h2>
        <form onSubmit={(event) => void handleSubmitReport(event)}>
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
        </form>
      </section>
    </div>
  )
}
