import { useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useTranslation } from '../i18n'
import { TwoStepSection } from './TwoStepSection'

/** Phase 5.1: any signed-in user changes their own password. */
export function AccountPage() {
  const { user } = useAuth()
  const { t } = useTranslation()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setDone(false)
    if (next !== confirm) {
      setError(t("The new passwords don't match."))
      return
    }
    setIsSaving(true)
    try {
      await api.changePassword(current, next)
      setCurrent('')
      setNext('')
      setConfirm('')
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Failed to change the password.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <main className="account-page">
      <h1>{t('Account')}</h1>
      {user && (
        <p>{t('Signed in as {name} ({email})', { name: user.full_name, email: user.email })}</p>
      )}
      <h2>{t('Change password')}</h2>
      <form onSubmit={(event) => void handleSubmit(event)}>
        <label htmlFor="current-password">{t('Current password')}</label>
        <input
          id="current-password"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          required
        />
        <label htmlFor="new-password">{t('New password')}</label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
          required
        />
        <label htmlFor="confirm-password">{t('New password again')}</label>
        <input
          id="confirm-password"
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
        {done && (
          <p role="status" className="status">
            {t("Password changed. You've been signed out everywhere else.")}
          </p>
        )}
        <button type="submit" disabled={isSaving}>
          {isSaving ? t('Saving…') : t('Change password')}
        </button>
      </form>
      <TwoStepSection />
    </main>
  )
}
