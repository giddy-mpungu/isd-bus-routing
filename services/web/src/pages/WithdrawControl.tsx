import { useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Student } from '../api/types'
import { Badge } from '../components/Badge'

/**
 * FERPA retention, for a transportation admin: mark a student as having
 * left the district (they stop riding that day; their data is deleted after
 * the end of the following school year), or undo it.
 */
export function WithdrawControl({
  student,
  onChanged,
}: {
  student: Student
  onChanged: () => Promise<void> | void
}) {
  const [picking, setPicking] = useState(false)
  const [on, setOn] = useState(() => new Date().toISOString().slice(0, 10))
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  async function run(action: () => Promise<unknown>) {
    setError(null)
    setIsSaving(true)
    try {
      await action()
      setPicking(false)
      await onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save.')
    } finally {
      setIsSaving(false)
    }
  }

  if (student.withdrawn_on) {
    return (
      <>
        <Badge tone="warning">
          Left {student.withdrawn_on}; data deleted after {student.delete_after}
        </Badge>{' '}
        <button
          type="button"
          disabled={isSaving}
          onClick={() => void run(() => api.reinstateStudent(student.id))}
        >
          Reinstate
        </button>
        {error && (
          <span role="alert" className="error">
            {' '}
            {error}
          </span>
        )}
      </>
    )
  }
  if (!picking) {
    return (
      <button type="button" onClick={() => setPicking(true)}>
        Withdraw
      </button>
    )
  }
  return (
    <span className="withdraw-control">
      <label htmlFor={`withdraw-${student.id}`}>Left the district on</label>{' '}
      <input
        id={`withdraw-${student.id}`}
        type="date"
        value={on}
        onChange={(event) => setOn(event.target.value)}
      />{' '}
      <button
        type="button"
        disabled={isSaving || !on}
        onClick={() => void run(() => api.withdrawStudent(student.id, on))}
      >
        Confirm withdrawal
      </button>{' '}
      <button type="button" onClick={() => setPicking(false)}>
        Cancel
      </button>
      {error && (
        <span role="alert" className="error">
          {' '}
          {error}
        </span>
      )}
    </span>
  )
}
