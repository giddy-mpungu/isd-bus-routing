import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { useTranslation } from '../i18n'

function tokenFromHash(): string {
  return new URLSearchParams(window.location.hash.slice(1)).get('token') ?? ''
}

/**
 * Phase 5.1: the page a one-time reset link opens. The token arrives in
 * the URL fragment and is removed from the address bar straight away,
 * so it doesn't linger in history or get copied along with the URL.
 */
export function ResetPasswordPage() {
  const { t } = useTranslation()
  const [token] = useState(tokenFromHash)
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    if (window.location.hash) {
      window.history.replaceState(null, '', window.location.pathname)
    }
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (next !== confirm) {
      setError(t("The passwords don't match."))
      return
    }
    setIsSaving(true)
    try {
      await api.resetPassword(token, next)
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Failed to set the password.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <main className="login-page">
      <form onSubmit={(event) => void handleSubmit(event)}>
        <h1>{t('Choose a password')}</h1>
        {done ? (
          <p role="status">
            {t('Your password is set.')} <Link to="/login">{t('Sign in with it.')}</Link>
          </p>
        ) : token === '' ? (
          <p role="alert" className="error">
            {t('This link is incomplete. Ask your transportation office for a new one.')}
          </p>
        ) : (
          <>
            <label htmlFor="reset-new-password">{t('New password')}</label>
            <input
              id="reset-new-password"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(event) => setNext(event.target.value)}
              required
            />
            <label htmlFor="reset-confirm-password">{t('New password again')}</label>
            <input
              id="reset-confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              required
            />
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button type="submit" disabled={isSaving}>
              {isSaving ? t('Saving…') : t('Set password')}
            </button>
          </>
        )}
      </form>
    </main>
  )
}
