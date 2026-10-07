import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { MfaStatus } from '../api/types'
import { MfaSetup, RecoveryCodes } from '../components/MfaSetup'
import { useTranslation } from '../i18n'

/** Phase 5.3: two-step sign-in on the Account page. */
export function TwoStepSection() {
  const { t } = useTranslation()
  const [status, setStatus] = useState<MfaStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [settingUp, setSettingUp] = useState(false)
  const [code, setCode] = useState('')
  const [newCodes, setNewCodes] = useState<string[] | null>(null)
  const [password, setPassword] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      setStatus(await api.getMfaStatus())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Failed to load two-step sign-in.'))
    }
  }, [t])

  useEffect(() => {
    let current = true
    api.getMfaStatus().then(
      (data) => {
        if (current) setStatus(data)
      },
      (err: unknown) => {
        if (current)
          setError(err instanceof ApiError ? err.message : t('Failed to load two-step sign-in.'))
      },
    )
    return () => {
      current = false
    }
  }, [t])

  async function run(action: () => Promise<void>) {
    setError(null)
    setIsSaving(true)
    try {
      await action()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Something went wrong.'))
    } finally {
      setIsSaving(false)
    }
  }

  function handleNewCodes(event: FormEvent) {
    event.preventDefault()
    void run(async () => {
      setNewCodes(await api.replaceRecoveryCodes(code))
      setCode('')
    })
  }

  function handleTurnOff(event: FormEvent) {
    event.preventDefault()
    void run(async () => {
      await api.disableMfa(password)
      setPassword('')
      await load()
    })
  }

  if (status === null) {
    return error ? (
      <p role="alert" className="error">
        {error}
      </p>
    ) : null
  }
  if (!status.allowed) {
    return null
  }

  return (
    <section className="two-step-section">
      <h2>{t('Two-step sign-in')}</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {newCodes ? (
        <RecoveryCodes codes={newCodes} onDone={() => void load().then(() => setNewCodes(null))} />
      ) : settingUp ? (
        <MfaSetup
          onDone={() => {
            setSettingUp(false)
            void load()
          }}
        />
      ) : status.enabled ? (
        <>
          <p>
            {t(
              status.recovery_codes_left === 1
                ? 'On. Signing in needs a code from your authenticator app. You have 1 recovery code left.'
                : 'On. Signing in needs a code from your authenticator app. You have {count} recovery codes left.',
              { count: status.recovery_codes_left },
            )}
          </p>
          <form onSubmit={handleNewCodes}>
            <label htmlFor="new-codes-code">
              {t('Code from your app, to make new recovery codes')}
            </label>
            <input
              id="new-codes-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              required
            />
            <button type="submit" disabled={isSaving}>
              {t('Make new recovery codes')}
            </button>
          </form>
          {status.required ? (
            <p className="status">{t('Your role needs two-step sign-in, so it stays on.')}</p>
          ) : (
            <form onSubmit={handleTurnOff}>
              <label htmlFor="mfa-off-password">{t('Password, to turn it off')}</label>
              <input
                id="mfa-off-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button type="submit" disabled={isSaving}>
                {t('Turn off two-step sign-in')}
              </button>
            </form>
          )}
        </>
      ) : (
        <>
          <p>
            {t(
              "Off. With it on, signing in also needs a code from an authenticator app on your phone, so a stolen password isn't enough.",
            )}
          </p>
          <button type="button" onClick={() => setSettingUp(true)}>
            {t('Turn on two-step sign-in')}
          </button>
        </>
      )}
    </section>
  )
}
