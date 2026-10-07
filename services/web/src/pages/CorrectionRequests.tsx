import { useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Correction } from '../api/types'
import { Badge, type BadgeTone } from '../components/Badge'
import { useTranslation, type Phrase } from '../i18n'

const STATUS: Record<Correction['status'], { label: Phrase; tone: BadgeTone }> = {
  open: { label: 'Waiting for an answer', tone: 'info' },
  accepted: { label: 'Corrected', tone: 'success' },
  declined: { label: 'Declined', tone: 'warning' },
}

/**
 * FERPA's right to request amendment, for one child on the Family page:
 * "Something's wrong?" opens a short form; earlier requests show their answer.
 */
export function CorrectionRequests({
  studentId,
  firstName,
}: {
  studentId: number
  firstName: string
}) {
  const { t } = useTranslation()
  const [requests, setRequests] = useState<Correction[]>([])
  const [open, setOpen] = useState(false)
  const [wrong, setWrong] = useState('')
  const [shouldSay, setShouldSay] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    let current = true
    api.getStudentCorrections(studentId).then(
      (rows) => {
        if (current) setRequests(rows)
      },
      () => {
        // Nothing to show if they can't be loaded; the form still works.
      },
    )
    return () => {
      current = false
    }
  }, [studentId])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSaving(true)
    try {
      const made = await api.requestCorrection(studentId, {
        what_is_wrong: wrong,
        should_say: shouldSay,
      })
      setRequests((rows) => [made, ...rows])
      setWrong('')
      setShouldSay('')
      setOpen(false)
      setSent(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Failed to send the request.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="correction-requests">
      {!open && (
        <button type="button" onClick={() => setOpen(true)}>
          {t("Something's wrong?")}
        </button>
      )}
      {sent && !open && (
        <p role="status" className="status">
          {t("Sent. The transportation office will look at it and you'll see the answer here.")}
        </p>
      )}
      {open && (
        <form onSubmit={(event) => void submit(event)}>
          <label htmlFor={`wrong-${studentId}`}>
            {t("What's wrong in {name}'s record?", { name: firstName })}
          </label>
          <textarea
            id={`wrong-${studentId}`}
            maxLength={1000}
            value={wrong}
            onChange={(event) => setWrong(event.target.value)}
            required
          />
          <label htmlFor={`should-${studentId}`}>{t('What should it say?')}</label>
          <textarea
            id={`should-${studentId}`}
            maxLength={1000}
            value={shouldSay}
            onChange={(event) => setShouldSay(event.target.value)}
            required
          />
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <button type="submit" disabled={isSaving}>
            {isSaving ? t('Sending…') : t('Send to the transportation office')}
          </button>{' '}
          <button type="button" onClick={() => setOpen(false)}>
            {t('Cancel')}
          </button>
        </form>
      )}
      {requests.length > 0 && (
        <ul className="correction-list">
          {requests.map((r) => (
            <li key={r.id}>
              <Badge tone={STATUS[r.status].tone}>{t(STATUS[r.status].label)}</Badge> “
              {r.what_is_wrong}” → “{r.should_say}”
              {r.response && (
                <div className="correction-answer">
                  {t('Answer: {answer}', { answer: r.response })}
                </div>
              )}
              {r.status === 'declined' && (
                <div className="correction-answer">
                  {t(
                    'If you disagree, you can ask the district for a hearing, and add a statement to the record.',
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
