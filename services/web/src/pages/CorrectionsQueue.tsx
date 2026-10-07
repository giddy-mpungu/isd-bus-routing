import { useCallback, useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Correction } from '../api/types'
import { Badge } from '../components/Badge'

/**
 * FERPA: families' correction requests, for transportation admins. Accept
 * after making the fix in the record, or decline with a reason; the family
 * sees the answer and is emailed.
 */
export function CorrectionsQueue() {
  const [showAll, setShowAll] = useState(false)
  const [rows, setRows] = useState<Correction[]>([])
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  const load = useCallback(async (all: boolean) => {
    try {
      setRows(await api.getCorrections(all ? 'all' : 'open'))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load the requests.')
    }
  }, [])

  useEffect(() => {
    let current = true
    api.getCorrections('open').then(
      (data) => {
        if (current) setRows(data)
      },
      (err: unknown) => {
        if (current)
          setError(err instanceof ApiError ? err.message : 'Failed to load the requests.')
      },
    )
    return () => {
      current = false
    }
  }, [])

  async function decide(row: Correction, decision: 'accepted' | 'declined') {
    setError(null)
    setBusyId(row.id)
    try {
      await api.decideCorrection(row.id, { decision, response: answers[row.id] ?? '' })
      await load(showAll)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save the answer.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="corrections-queue">
      <h2>Record corrections</h2>
      <p className="status">
        Families ask here for a student&apos;s record to be corrected. Make the fix in the record
        first, then accept; or decline and say why. Families see the answer and are emailed.
      </p>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={showAll}
          onChange={(event) => {
            setShowAll(event.target.checked)
            void load(event.target.checked)
          }}
        />{' '}
        Show answered requests too
      </label>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {rows.length === 0 && <p className="status">No requests waiting.</p>}
      <ul className="corrections-list">
        {rows.map((r) => (
          <li key={r.id}>
            <p>
              <strong>{r.student_name}</strong>, asked by {r.requested_by} on{' '}
              {new Date(r.created_at).toLocaleDateString()}{' '}
              {r.status !== 'open' && (
                <Badge tone={r.status === 'accepted' ? 'success' : 'warning'}>{r.status}</Badge>
              )}
            </p>
            <p>What&apos;s wrong: {r.what_is_wrong}</p>
            <p>Should say: {r.should_say}</p>
            {r.status === 'open' ? (
              <>
                <label htmlFor={`answer-${r.id}`}>Answer to the family</label>
                <textarea
                  id={`answer-${r.id}`}
                  maxLength={1000}
                  value={answers[r.id] ?? ''}
                  onChange={(event) => setAnswers((a) => ({ ...a, [r.id]: event.target.value }))}
                />
                <button
                  type="button"
                  disabled={busyId === r.id || !(answers[r.id] ?? '').trim()}
                  onClick={() => void decide(r, 'accepted')}
                >
                  Accept (fixed)
                </button>{' '}
                <button
                  type="button"
                  disabled={busyId === r.id || !(answers[r.id] ?? '').trim()}
                  onClick={() => void decide(r, 'declined')}
                >
                  Decline
                </button>
              </>
            ) : (
              <p>Answer: {r.response}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
