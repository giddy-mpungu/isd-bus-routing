import { useCallback, useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { AssignmentStatus, DriverAssignment } from '../api/types'

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
  const [serviceDate] = useState(today)
  const [assignments, setAssignments] = useState<DriverAssignment[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [busyAssignmentId, setBusyAssignmentId] = useState<number | null>(null)

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

  return (
    <div className="driver-page">
      <h1>My runs — {serviceDate}</h1>
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
            <div className="driver-run-status">Status: {STATUS_LABELS[a.status]}</div>
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
    </div>
  )
}
