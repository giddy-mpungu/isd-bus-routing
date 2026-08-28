import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Navigate, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { CurrentUser } from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { LoginPage } from './LoginPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, login: vi.fn(), getCurrentUser: vi.fn() }
})

function renderLoginPage() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
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

describe('LoginPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    // AuthProvider's initial mount check — no session yet.
    vi.mocked(api.getCurrentUser).mockRejectedValue(new Error('not logged in'))
  })

  it('logs in and navigates to the schedule page on success', async () => {
    vi.mocked(api.login).mockResolvedValue(undefined)
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
})
