import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import * as api from '../api/client'
import { ApiError } from '../api/client'

/**
 * Phase 5.2: ask for a reset link by email. The answer is the same
 * whether or not the address has an account.
 */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSending, setIsSending] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSending(true)
    try {
      setSent(await api.forgotPassword(email))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to send the email.')
    } finally {
      setIsSending(false)
    }
  }

  return (
    <main className="login-page">
      <form onSubmit={(event) => void handleSubmit(event)}>
        <h1>Forgot your password?</h1>
        {sent ? (
          <p role="status">
            {sent} The link works for a short time and only once.{' '}
            <Link to="/login">Back to sign in</Link>
          </p>
        ) : (
          <>
            <p>
              Enter your account&apos;s email and we&apos;ll send you a link to choose a new one.
            </p>
            <label htmlFor="forgot-email">Email</label>
            <input
              id="forgot-email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button type="submit" disabled={isSending}>
              {isSending ? 'Sending…' : 'Email me a link'}
            </button>
            <p className="login-help">
              <Link to="/login">Back to sign in</Link>
            </p>
          </>
        )}
      </form>
    </main>
  )
}
