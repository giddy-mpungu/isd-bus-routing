import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { CurrentUser } from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { AppLayout } from './AppLayout'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getCurrentUser: vi.fn() }
})

function renderLayout() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <AppLayout>
          <p>page content</p>
        </AppLayout>
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
}

describe('AppLayout', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('shows Schedule/Setup and not My Runs for a dispatcher', async () => {
    vi.mocked(api.getCurrentUser).mockResolvedValue(dispatcherUser)
    renderLayout()
    await waitFor(() => expect(screen.getByRole('link', { name: 'Schedule' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Setup' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'My Runs' })).not.toBeInTheDocument()
  })

  it('shows My Runs and not Schedule/Setup for a driver', async () => {
    vi.mocked(api.getCurrentUser).mockResolvedValue({ ...dispatcherUser, role: 'driver' })
    renderLayout()
    await waitFor(() => expect(screen.getByRole('link', { name: 'My Runs' })).toBeInTheDocument())
    expect(screen.queryByRole('link', { name: 'Schedule' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Setup' })).not.toBeInTheDocument()
  })

  it('shows no nav links when logged out', async () => {
    vi.mocked(api.getCurrentUser).mockRejectedValue(new Error('401'))
    renderLayout()
    await waitFor(() => expect(screen.getByText('page content')).toBeInTheDocument())
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })
})
