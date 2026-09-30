import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [emailEnabled, setEmailEnabled] = useState(false)

  useEffect(() => {
    let current = true
    api.getAuthOptions().then(
      (options) => {
        if (current) setEmailEnabled(options.email_enabled)
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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await login(email, password)
      navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <form onSubmit={(event) => void handleSubmit(event)}>
        <h1>isd-bus-routing</h1>
        <p>Dispatcher console</p>

        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="username"
          required
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
        />

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}

        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="login-help">
          {emailEnabled ? (
            <Link to="/forgot-password">Forgot your password?</Link>
          ) : (
            'Forgot your password? Ask your transportation office for a reset link.'
          )}
        </p>
      </form>
    </main>
  )
}
