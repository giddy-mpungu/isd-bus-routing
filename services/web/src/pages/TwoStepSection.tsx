import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { MfaStatus } from '../api/types'
import { MfaSetup, RecoveryCodes } from '../components/MfaSetup'

/** Phase 5.3: two-step sign-in on the Account page. */
export function TwoStepSection() {
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
      setError(err instanceof ApiError ? err.message : 'Failed to load two-step sign-in.')
    }
  }, [])

  useEffect(() => {
    let current = true
    api.getMfaStatus().then(
      (data) => {
        if (current) setStatus(data)
      },
      (err: unknown) => {
        if (current)
          setError(err instanceof ApiError ? err.message : 'Failed to load two-step sign-in.')
      },
    )
    return () => {
      current = false
    }
  }, [])

  async function run(action: () => Promise<void>) {
    setError(null)
    setIsSaving(true)
    try {
      await action()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
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
      <h2>Two-step sign-in</h2>
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
            On. Signing in needs a code from your authenticator app. You have{' '}
            {status.recovery_codes_left} recovery codes left.
          </p>
          <form onSubmit={handleNewCodes}>
            <label htmlFor="new-codes-code">Code from your app, to make new recovery codes</label>
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
              Make new recovery codes
            </button>
          </form>
          {status.required ? (
            <p className="status">Your role needs two-step sign-in, so it stays on.</p>
          ) : (
            <form onSubmit={handleTurnOff}>
              <label htmlFor="mfa-off-password">Password, to turn it off</label>
              <input
                id="mfa-off-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button type="submit" disabled={isSaving}>
                Turn off two-step sign-in
              </button>
            </form>
          )}
        </>
      ) : (
        <>
          <p>
            Off. With it on, signing in also needs a code from an authenticator app on your phone,
            so a stolen password isn&apos;t enough.
          </p>
          <button type="button" onClick={() => setSettingUp(true)}>
            Turn on two-step sign-in
          </button>
        </>
      )}
    </section>
  )
}
