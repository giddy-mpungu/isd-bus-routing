import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { useTranslation } from '../i18n'

function tokenFromHash(): string {
  return new URLSearchParams(window.location.hash.slice(1)).get('token') ?? ''
}

/**
 * Phase 5.5: where "stop these emails" in a bus-time email leads. It asks
 * for a click rather than acting on page load, because mail security
 * scanners open links in emails by themselves.
 */
export function EmailPreferencesPage() {
  const { t } = useTranslation()
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
      setError(err instanceof ApiError ? err.message : t('Failed to save.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <main className="login-page">
      <form onSubmit={(event) => event.preventDefault()}>
        <h1>{t('Bus time emails')}</h1>
        {done ? (
          <p role="status">
            {t("Done: you won't get bus time emails any more.")}{' '}
            <Link to="/family">{t('Turn them back on from the Family page.')}</Link>
          </p>
        ) : token === '' ? (
          <p role="alert" className="error">
            {t('This link is incomplete.')}{' '}
            <Link to="/family">{t('Turn bus time emails off on the Family page.')}</Link>
          </p>
        ) : (
          <>
            <p>{t("Stop emails telling you when your child's bus time changes?")}</p>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button type="button" onClick={() => void stop()} disabled={isSaving}>
              {isSaving ? t('Saving…') : t('Stop bus time emails')}
            </button>
          </>
        )}
      </form>
    </main>
  )
}
