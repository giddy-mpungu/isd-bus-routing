import { useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'

/**
 * Phase 5.5: a parent's switch for "bus time changed" emails. On by
 * default; hidden for accounts it doesn't apply to (student logins).
 */
export function EtaEmailSetting() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    let current = true
    api.getNotificationSettings().then(
      (data) => {
        if (current) setEnabled(data.eta_emails)
      },
      () => {
        // Not a parent account (or offline): nothing to show.
      },
    )
    return () => {
      current = false
    }
  }, [])

  async function toggle(next: boolean) {
    setError(null)
    setIsSaving(true)
    try {
      setEnabled((await api.updateNotificationSettings({ eta_emails: next })).eta_emails)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save.')
    } finally {
      setIsSaving(false)
    }
  }

  if (enabled === null) return null
  return (
    <section className="eta-email-setting">
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={enabled}
          disabled={isSaving}
          onChange={(event) => void toggle(event.target.checked)}
        />{' '}
        Email me when my child&apos;s bus time changes by 10 minutes or more
      </label>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </section>
  )
}
