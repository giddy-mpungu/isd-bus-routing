import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Navigate, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { CurrentUser } from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { LoginPage } from './LoginPage'
import { axeViolations } from '../test/axe'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    login: vi.fn(),
    getCurrentUser: vi.fn(),
    getAuthOptions: vi.fn(),
    verifyMfa: vi.fn(),
    startMfaSetup: vi.fn(),
    confirmMfa: vi.fn(),
  }
})

function renderLoginPage(entry = '/login') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/schedule" element={<p>schedule page</p>} />
          {/* Mirrors App.tsx's real "/" role redirect closely enough for
              this test's purposes — LoginPage itself just navigates to
              "/" and lets that route decide the destination. */}
          <Route path="/" element={<Navigate to="/schedule" replace />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

const dispatcherUser: CurrentUser = {
  id: 1,
  email: 'a@example.org',
  full_name: 'A Dispatcher',
  role: 'dispatcher',
  is_active: true,
  driver_id: null,
  school_id: null,
  student_id: null,
}

// Every state these tests reach is checked against WCAG 2.1 A/AA.
afterEach(async () => {
  expect(await axeViolations()).toEqual([])
})

describe('LoginPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getAuthOptions).mockResolvedValue({ email_enabled: false })
    // AuthProvider's initial mount check — no session yet.
    vi.mocked(api.getCurrentUser).mockRejectedValue(new Error('not logged in'))
  })

  it('logs in and navigates to the schedule page on success', async () => {
    vi.mocked(api.login).mockResolvedValue({
      access_token: 't',
      token_type: 'bearer',
      mfa: null,
      recovery_codes_left: null,
    })
    vi.mocked(api.getCurrentUser).mockRejectedValueOnce(new Error('not logged in yet'))
    vi.mocked(api.getCurrentUser).mockResolvedValueOnce(dispatcherUser)

    renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/email/i), 'a@example.org')
    await user.type(screen.getByLabelText(/password/i), 'correct-horse')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => expect(screen.getByText('schedule page')).toBeInTheDocument())
    expect(api.login).toHaveBeenCalledWith('a@example.org', 'correct-horse')
  })

  it('shows the server error message on failed login', async () => {
    vi.mocked(api.login).mockRejectedValue(new ApiError(401, 'Incorrect email or password'))

    renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/email/i), 'a@example.org')
    await user.type(screen.getByLabelText(/password/i), 'wrong')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Incorrect email or password'),
    )
  })

  it('offers "Forgot your password?" only when email is set up', async () => {
    vi.mocked(api.getCurrentUser).mockRejectedValue(new ApiError(401, 'Not authenticated'))
    renderLoginPage()
    expect(
      await screen.findByText(
        'Forgot your password? Ask your transportation office for a reset link.',
      ),
    ).toBeInTheDocument()
  })

  it('links to the forgot-password page when email is on', async () => {
    vi.mocked(api.getCurrentUser).mockRejectedValue(new ApiError(401, 'Not authenticated'))
    vi.mocked(api.getAuthOptions).mockResolvedValue({ email_enabled: true })
    renderLoginPage()
    expect(await screen.findByRole('link', { name: 'Forgot your password?' })).toHaveAttribute(
      'href',
      '/forgot-password',
    )
  })

  it('asks for the authenticator code after a correct password', async () => {
    vi.mocked(api.login).mockResolvedValue({
      access_token: null,
      token_type: 'bearer',
      mfa: 'verify',
      recovery_codes_left: null,
    })
    vi.mocked(api.verifyMfa).mockResolvedValue({
      access_token: 't',
      token_type: 'bearer',
      mfa: null,
      recovery_codes_left: null,
    })
    vi.mocked(api.getCurrentUser)
      .mockRejectedValueOnce(new Error('not logged in yet'))
      .mockResolvedValueOnce(dispatcherUser)
    renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Email'), 'dispatcher@example.org')
    await user.type(screen.getByLabelText('Password'), 'correct-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'Two-step sign-in' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(api.verifyMfa).toHaveBeenCalledWith('123456'))
    expect(await screen.findByText('schedule page')).toBeInTheDocument()
  })

  it('goes back to the password when the second step timed out', async () => {
    vi.mocked(api.login).mockResolvedValue({
      access_token: null,
      token_type: 'bearer',
      mfa: 'verify',
      recovery_codes_left: null,
    })
    vi.mocked(api.verifyMfa).mockRejectedValue(
      new ApiError(401, 'Your sign-in timed out. Enter your password again.'),
    )
    renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Email'), 'dispatcher@example.org')
    await user.type(screen.getByLabelText('Password'), 'correct-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await user.type(await screen.findByLabelText('Code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your sign-in timed out.')
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
  })

  it('walks staff through setting up an authenticator', async () => {
    vi.mocked(api.login).mockResolvedValue({
      access_token: null,
      token_type: 'bearer',
      mfa: 'setup',
      recovery_codes_left: null,
    })
    vi.mocked(api.startMfaSetup).mockResolvedValue({
      secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP',
      otpauth_uri:
        'otpauth://totp/isd-bus-routing:d%40example.org?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP',
    })
    vi.mocked(api.confirmMfa).mockResolvedValue({ recovery_codes: ['AAAAA-BBBBB', 'CCCCC-DDDDD'] })
    vi.mocked(api.getCurrentUser)
      .mockRejectedValueOnce(new Error('not logged in yet'))
      .mockResolvedValueOnce(dispatcherUser)
    renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Email'), 'dispatcher@example.org')
    await user.type(screen.getByLabelText('Password'), 'correct-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(
      await screen.findByRole('heading', { name: 'Set up two-step sign-in' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('img', { name: 'QR code for your authenticator app' }),
    ).toBeInTheDocument()
    expect(screen.getByText('JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP')).toBeInTheDocument()
    await user.type(screen.getByLabelText('6-digit code'), '654321')
    await user.click(screen.getByRole('button', { name: 'Turn on two-step sign-in' }))

    const codes = await screen.findByRole('region', { name: 'Recovery codes' })
    expect(codes).toHaveTextContent('AAAAA-BBBBB')
    expect(api.confirmMfa).toHaveBeenCalledWith('654321')
    await user.click(screen.getByRole('button', { name: "I've saved them" }))
    expect(await screen.findByText('schedule page')).toBeInTheDocument()
  })

  it('offers single sign-on when the district has it', async () => {
    vi.mocked(api.getAuthOptions).mockResolvedValue({
      email_enabled: false,
      sso_label: 'your district account',
    })
    renderLoginPage()
    const link = await screen.findByRole('link', { name: 'Sign in with your district account' })
    expect(link).toHaveAttribute('href', api.ssoStartUrl())
    expect(api.ssoStartUrl()).toMatch(/\/auth\/oidc\/start$/)
  })

  it('has no single sign-on button when it is off', async () => {
    renderLoginPage()
    await screen.findByText(/Forgot your password\?/)
    expect(screen.queryByRole('link', { name: /Sign in with/ })).not.toBeInTheDocument()
  })

  it('explains why single sign-on sent the browser back', async () => {
    renderLoginPage('/login?sso_error=no_account')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      "There's no account for that district email here.",
    )
  })

  it('asks for our code after single sign-on when the district reported none', async () => {
    renderLoginPage('/login?mfa=verify')
    expect(await screen.findByRole('heading', { name: 'Two-step sign-in' })).toBeInTheDocument()
  })
})
