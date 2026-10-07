import { useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Student, StudentAccess } from '../api/types'

/**
 * FERPA: who at the district saw this student's information, for a
 * transportation admin (one line per person, kind of view and day).
 */
export function AccessLogPanel({ student }: { student: Student }) {
  const [rows, setRows] = useState<StudentAccess[] | null>(null)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    setError(null)
    try {
      setRows(await api.getStudentAccessLog(student.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load who viewed this student.')
    }
  }

  return (
    <>
      <button type="button" onClick={() => void toggle()} aria-expanded={open}>
        {open ? 'Hide who viewed' : 'Who viewed'}
      </button>
      {open && (
        <div
          className="access-log-panel"
          role="region"
          aria-label={`Who viewed ${student.full_name}`}
        >
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {rows && rows.length === 0 && (
            <p className="status">Nobody has viewed this student yet.</p>
          )}
          {rows && rows.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>First viewed that day</th>
                  <th>Who</th>
                  <th>Role</th>
                  <th>What</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.day}-${r.user_id}-${r.what}`}>
                    <td>{new Date(r.first_at).toLocaleString()}</td>
                    <td>{r.user_name}</td>
                    <td>{r.user_role.replace(/_/g, ' ')}</td>
                    <td>{r.what_label}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  )
}
