import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import * as api from '../api/client'
import { ApiError } from '../api/client'

function tokenFromHash(): string {
  return new URLSearchParams(window.location.hash.slice(1)).get('token') ?? ''
}

/**
 * Phase 5.5: where "stop these emails" in a bus-time email leads. It asks
 * for a click rather than acting on page load, because mail security
 * scanners open links in emails by themselves.
 */
export function EmailPreferencesPage() {
  const [token] = useState(tokenFromHash)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    if (window.location.hash) {
      window.history.replaceState(null, '', window.location.pathname)
    }
  }, [])

  async function stop() {
    setError(null)
    setIsSaving(true)
    try {
      await api.optOutOfEtaEmails(token)
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <main className="login-page">
      <form onSubmit={(event) => event.preventDefault()}>
        <h1>Bus time emails</h1>
        {done ? (
          <p role="status">
            Done: you won&apos;t get bus time emails any more. You can turn them back on from the{' '}
            <Link to="/family">Family page</Link>.
          </p>
        ) : token === '' ? (
          <p role="alert" className="error">
            This link is incomplete. You can turn bus time emails off on the{' '}
            <Link to="/family">Family page</Link>.
          </p>
        ) : (
          <>
            <p>Stop emails telling you when your child&apos;s bus time changes?</p>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button type="button" onClick={() => void stop()} disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Stop bus time emails'}
            </button>
          </>
        )}
      </form>
    </main>
  )
}
