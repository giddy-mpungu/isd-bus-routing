import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { MfaStep } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { MfaSetup } from '../components/MfaSetup'
import { useTranslation, type Phrase } from '../i18n'

// Why single sign-on sent the browser back here (routers/sso.py).
const SSO_ERRORS: Record<string, Phrase> = {
  no_account:
    "There's no account for that district email here. Ask your transportation office to add you.",
  not_for_role: 'Your account signs in with its email and password, not the district account.',
  linked_elsewhere:
    'That email is linked to a different district account. Ask your transportation office to unlink it.',
  no_email: "The district sign-in didn't share a verified email address.",
  cancelled: 'Sign-in with the district account was cancelled.',
  expired: 'That sign-in took too long or was interrupted. Try again.',
  provider_unreachable:
    "The district sign-in couldn't be reached. Try again, or use your password.",
  failed: "The district sign-in couldn't be completed. Try again, or use your password.",
}

function stepFrom(value: string | null): MfaStep | null {
  return value === 'verify' || value === 'setup' ? value : null
}

export function LoginPage() {
  const { user, login, completeSignIn } = useAuth()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [searchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  // Why single sign-on failed, shown until the next attempt.
  const [ssoError, setSsoError] = useState<Phrase | null>(() => {
    const reason = searchParams.get('sso_error')
    return reason ? (SSO_ERRORS[reason] ?? SSO_ERRORS.failed) : null
  })
  const shownError = error ?? (ssoError ? t(ssoError) : null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [emailEnabled, setEmailEnabled] = useState(false)
  const [ssoLabel, setSsoLabel] = useState<string | null>(null)
  // Phase 5.3: the second step, once the password (or single sign-on,
  // when the district's two-step check wasn't reported) was right.
  const [step, setStep] = useState<MfaStep | null>(() => stepFrom(searchParams.get('mfa')))
  const [code, setCode] = useState('')

  useEffect(() => {
    let current = true
    api.getAuthOptions().then(
      (options) => {
        if (current) {
          setEmailEnabled(options.email_enabled)
          setSsoLabel(options.sso_label ?? null)
        }
      },
      () => {
        // Keep the "ask your transportation office" hint.
      },
    )
    return () => {
      current = false
    }
  }, [])

  if (user) {
    // Let the "/" route's role-aware redirect decide the destination
    // (dispatcher/admin -> /schedule, driver -> /driver) rather than
    // hardcoding one role's landing page here.
    return <Navigate to="/" replace />
  }

  async function finish() {
    await completeSignIn()
    navigate('/')
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSsoError(null)
    setIsSubmitting(true)
    try {
      const next = await login(email, password)
      if (next) {
        setPassword('')
        setStep(next)
      } else {
        navigate('/')
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Login failed.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleVerify(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      const result = await api.verifyMfa(code)
      if (result.recovery_codes_left !== null && result.recovery_codes_left <= 3) {
        window.alert(
          t(
            result.recovery_codes_left === 1
              ? 'You have 1 recovery code left. Make new ones on your Account page.'
              : 'You have {count} recovery codes left. Make new ones on your Account page.',
            { count: result.recovery_codes_left },
          ),
        )
      }
      await finish()
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // The 5-minute window after the password ran out.
        setStep(null)
      }
      setError(err instanceof ApiError ? err.message : t('Sign-in failed.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  if (step === 'setup') {
    return (
      <main className="login-page login-page-wide">
        <div className="login-card">
          <h1>{t('Set up two-step sign-in')}</h1>
          <p>
            {t(
              'Your role can see student information, so signing in needs a code from an authenticator app as well as your password. This takes about a minute.',
            )}
          </p>
          <MfaSetup onDone={() => void finish()} />
        </div>
      </main>
    )
  }

  if (step === 'verify') {
    return (
      <main className="login-page">
        <form onSubmit={(event) => void handleVerify(event)}>
          <h1>{t('Two-step sign-in')}</h1>
          <p>{t('Enter the 6-digit code from your authenticator app.')}</p>
          <label htmlFor="mfa-code">{t('Code')}</label>
          <input
            id="mfa-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={20}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            required
            autoFocus
          />
          {shownError && (
            <p role="alert" className="error">
              {shownError}
            </p>
          )}
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? t('Checking…') : t('Sign in')}
          </button>
          <p className="login-help">
            {t(
              'Lost your phone? Enter one of your recovery codes instead, or ask your transportation office to reset two-step sign-in.',
            )}
          </p>
        </form>
      </main>
    )
  }

  return (
    <main className="login-page">
      <form onSubmit={(event) => void handleSubmit(event)}>
        <h1>isd-bus-routing</h1>
        <p>{t('School transportation')}</p>

        {ssoLabel && (
          <>
            <a className="sso-button" href={api.ssoStartUrl()}>
              {t('Sign in with {provider}', { provider: ssoLabel })}
            </a>
            <p className="login-or">{t('or with your email and password')}</p>
          </>
        )}

        <label htmlFor="email">{t('Email')}</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="username"
          required
        />

        <label htmlFor="password">{t('Password')}</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
        />

        {shownError && (
          <p role="alert" className="error">
            {shownError}
          </p>
        )}

        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? t('Signing in…') : t('Sign in')}
        </button>
        <p className="login-help">
          {emailEnabled ? (
            <Link to="/forgot-password">{t('Forgot your password?')}</Link>
          ) : (
            t('Forgot your password? Ask your transportation office for a reset link.')
          )}
        </p>
      </form>
    </main>
  )
}
