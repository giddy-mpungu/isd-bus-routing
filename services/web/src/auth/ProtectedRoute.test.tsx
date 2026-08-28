import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { CurrentUser } from '../api/types'
import { AuthProvider } from './AuthContext'
import { ProtectedRoute } from './ProtectedRoute'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getCurrentUser: vi.fn() }
})

function renderProtected() {
  return render(
    <MemoryRouter initialEntries={['/schedule']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<p>login page</p>} />
          <Route
            path="/schedule"
            element={
              <ProtectedRoute allowedRoles={['dispatcher', 'transportation_admin']}>
                <p>schedule page</p>
              </ProtectedRoute>
            }
          />
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

describe('ProtectedRoute', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('redirects to /login when there is no session', async () => {
    vi.mocked(api.getCurrentUser).mockRejectedValue(new Error('401'))
    renderProtected()
    await waitFor(() => expect(screen.getByText('login page')).toBeInTheDocument())
  })

  it('shows a not-authorized message for a role outside allowedRoles', async () => {
    vi.mocked(api.getCurrentUser).mockResolvedValue({ ...dispatcherUser, role: 'driver' })
    renderProtected()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/isn't authorized/i))
  })

  it('renders the protected content for an allowed role', async () => {
    vi.mocked(api.getCurrentUser).mockResolvedValue(dispatcherUser)
    renderProtected()
    await waitFor(() => expect(screen.getByText('schedule page')).toBeInTheDocument())
  })
})
