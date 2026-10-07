import { useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { MfaSetup as MfaSetupData } from '../api/types'
import { useTranslation } from '../i18n'
import { QrCode } from './QrCode'

/** Recovery codes, shown once, with a way to keep them. */
export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  const { t } = useTranslation()
  return (
    <div className="recovery-codes" role="region" aria-label={t('Recovery codes')}>
      <p>
        <strong>{t('Save these recovery codes')}</strong>{' '}
        {t(
          "somewhere safe, away from your phone (print them, or keep them in a password manager). Each one signs you in once if you lose your phone. They won't be shown again.",
        )}
      </p>
      <ul>
        {codes.map((c) => (
          <li key={c}>
            <code>{c}</code>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard.writeText(codes.join('\n')).then(
            () => setCopied(true),
            () => setCopied(false),
          )
        }}
      >
        {copied ? t('Copied') : t('Copy codes')}
      </button>{' '}
      <button type="button" onClick={onDone}>
        {t("I've saved them")}
      </button>
    </div>
  )
}

/**
 * Phase 5.3: set up an authenticator app. Used at sign-in (when a role
 * needs it) and from the Account page. Calls onDone once the recovery
 * codes have been seen.
 */
export function MfaSetup({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const [setup, setSetup] = useState<MfaSetupData | null>(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    let current = true
    api.startMfaSetup().then(
      (data) => {
        if (current) setSetup(data)
      },
      (err: unknown) => {
        if (current) setError(err instanceof ApiError ? err.message : t('Failed to start setup.'))
      },
    )
    return () => {
      current = false
    }
  }, [])

  async function handleConfirm(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSaving(true)
    try {
      setCodes((await api.confirmMfa(code)).recovery_codes)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Failed to check the code.'))
    } finally {
      setIsSaving(false)
    }
  }

  if (codes) {
    return <RecoveryCodes codes={codes} onDone={onDone} />
  }
  return (
    <div className="mfa-setup">
      <ol>
        <li>
          {t(
            'Open an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, or your password manager) and add an account.',
          )}
        </li>
        <li>{t('Scan this QR code, or type the setup key instead.')}</li>
        <li>{t('Enter the 6-digit code the app shows.')}</li>
      </ol>
      {setup && (
        <>
          <QrCode value={setup.otpauth_uri} label={t('QR code for your authenticator app')} />
          <p>
            {t('Setup key:')}{' '}
            <code className="mfa-secret">{setup.secret.replace(/(.{4})/g, '$1 ')}</code>
          </p>
        </>
      )}
      <form onSubmit={(event) => void handleConfirm(event)}>
        <label htmlFor="mfa-setup-code">{t('6-digit code')}</label>
        <input
          id="mfa-setup-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(event) => setCode(event.target.value)}
          required
        />
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <button type="submit" disabled={isSaving || setup === null}>
          {isSaving ? t('Checking…') : t('Turn on two-step sign-in')}
        </button>
      </form>
    </div>
  )
}
