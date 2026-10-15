import { useCallback, useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Announcement, SchoolAssignment, SchoolBells } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { STATUS_LABELS, STATUS_TONES } from '../assignmentStatus'
import { Badge } from '../components/Badge'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatMinuteOfDay(minute: number): string {
  const hours = Math.floor(minute / 60)
  const mins = minute % 60
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`
}

/** The school's bell times and coming special days, as transportation has them. */
function SchoolBellsPanel({ schoolId }: { schoolId: number }) {
  const [bells, setBells] = useState<SchoolBells | null>(null)

  useEffect(() => {
    let current = true
    api.getSchoolBells(schoolId).then(
      (read) => {
        if (current) setBells(read)
      },
      () => {
        // Nothing to show; the rest of the page still works.
      },
    )
    return () => {
      current = false
    }
  }, [schoolId])

  if (bells === null) return null
  return (
    <section className="school-bells">
      <h2>Bell schedule</h2>
      {bells.schedules.length === 0 ? (
        <p>Transportation hasn&apos;t entered this school&apos;s bell times yet.</p>
      ) : (
        <ul>
          {bells.schedules.map((s) => (
            <li key={s.id}>
              {s.name}: first bell {formatMinuteOfDay(s.first_bell_minute)}, dismissal{' '}
              {formatMinuteOfDay(s.dismissal_minute)}
              {s.is_regular && ' (regular)'}
            </li>
          ))}
        </ul>
      )}
      {bells.upcoming_days.length > 0 && (
        <>
          <h3>Coming special days</h3>
          <ul>
            {bells.upcoming_days.map((d) => (
              <li key={d.id}>
                {d.service_date}: {d.schedule_name}
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="status">
        Something wrong here? Tell the transportation office, which keeps the bell times buses run
        to.
      </p>
    </section>
  )
}

export function SchoolAdminPage() {
  const { user } = useAuth()
  const [serviceDate] = useState(today)
  const [assignments, setAssignments] = useState<SchoolAssignment[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  // spec section 17: "Transportation notices" for this school_admin's
  // own school -- GET /announcements/mine is already scoped server-side
  // (routers/announcements.py's _recipient_school_ids).
  const [announcements, setAnnouncements] = useState<Announcement[]>([])

  const loadAssignments = useCallback(async (date: string) => {
    setErrorMessage(null)
    try {
      setAssignments(await api.getSchoolAssignments(date))
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to load buses for today.')
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

  return (
    <div className="school-admin-page">
      <h1>Buses serving my school — {serviceDate}</h1>

      {announcements.length > 0 && (
        <section className="announcements-panel">
          <h2>Transportation notices</h2>
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
        <p className="status">No buses scheduled for today yet.</p>
      )}

      <ul className="school-admin-assignment-list">
        {assignments.map((a) => (
          <li key={a.id} className="school-admin-assignment-card">
            <div className="school-admin-assignment-time">
              {a.direction.toUpperCase()}: {formatMinuteOfDay(a.start_minute)} –{' '}
              {formatMinuteOfDay(a.end_minute)}
            </div>
            <div className="school-admin-assignment-driver">Driver: {a.driver_full_name}</div>
            <div className="school-admin-assignment-vehicle">Vehicle: {a.vehicle_label}</div>
            <div className="school-admin-assignment-status">
              Status: <Badge tone={STATUS_TONES[a.status]}>{STATUS_LABELS[a.status]}</Badge>
            </div>
            {a.expected_school_minute != null && a.planned_school_minute != null && (
              <div className="school-admin-assignment-eta">
                {a.direction === 'am' ? 'At school' : 'Leaves school'}:{' '}
                <strong>{formatMinuteOfDay(a.expected_school_minute)}</strong>
                {a.expected_school_minute !== a.planned_school_minute &&
                  ` (planned ${formatMinuteOfDay(a.planned_school_minute)})`}{' '}
                {a.running_late && <Badge tone="warning">Running {a.delay_minutes} min late</Badge>}{' '}
                {a.eta_basis && <span className="school-admin-eta-basis">{a.eta_basis}</span>}
              </div>
            )}
          </li>
        ))}
      </ul>
      {user?.school_id != null && <SchoolBellsPanel schoolId={user.school_id} />}
    </div>
  )
}
