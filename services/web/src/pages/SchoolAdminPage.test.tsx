import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { CurrentUser, SchoolAssignment } from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { SchoolAdminPage } from './SchoolAdminPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getCurrentUser: vi.fn(),
    getSchoolAssignments: vi.fn(),
    getMyAnnouncements: vi.fn(),
  }
})

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

const schoolAdminUser: CurrentUser = {
  id: 1,
  email: 'schooladmin@example.org',
  full_name: 'Sam SchoolAdmin',
  role: 'school_admin',
  is_active: true,
  driver_id: null,
  school_id: 1,
  student_id: null,
}

const assignment: SchoolAssignment = {
  id: 100,
  run_id: 10,
  service_date: today(),
  direction: 'am',
  window_earliest: 360,
  window_latest: 410,
  driver_full_name: 'Jordan Driver',
  vehicle_label: 'Bus 101',
  start_minute: 360,
  end_minute: 410,
  status: 'sent',
  locked: false,
}

function renderPage() {
  vi.mocked(api.getCurrentUser).mockResolvedValue(schoolAdminUser)
  return render(
    <AuthProvider>
      <SchoolAdminPage />
    </AuthProvider>,
  )
}

describe('SchoolAdminPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([])
  })

  it('renders a bus card with resolved driver/vehicle names, direction, and time window', async () => {
    vi.mocked(api.getSchoolAssignments).mockResolvedValue([assignment])
    renderPage()

    await waitFor(() => expect(screen.getByText('Driver: Jordan Driver')).toBeInTheDocument())
    expect(screen.getByText('Vehicle: Bus 101')).toBeInTheDocument()
    expect(screen.getByText('AM: 06:00 – 06:50')).toBeInTheDocument()
    expect(screen.getByText('Sent')).toBeInTheDocument()
  })

  it('shows a friendly message when no buses are scheduled yet', async () => {
    vi.mocked(api.getSchoolAssignments).mockResolvedValue([])
    renderPage()

    await waitFor(() =>
      expect(screen.getByText('No buses scheduled for today yet.')).toBeInTheDocument(),
    )
  })

  it('renders transportation notices scoped to this school', async () => {
    vi.mocked(api.getSchoolAssignments).mockResolvedValue([])
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([
      {
        id: 1,
        message: 'Riverside dismissal moved up 15 minutes today.',
        category: 'general',
        audience: 'family',
        school_id: 1,
        created_at: '2026-09-14T12:00:00Z',
      },
    ])
    renderPage()

    await waitFor(() =>
      expect(
        screen.getByText(/Riverside dismissal moved up 15 minutes today\./),
      ).toBeInTheDocument(),
    )
  })

  it('shows an error message when loading assignments fails', async () => {
    const { ApiError } = await import('../api/client')
    vi.mocked(api.getSchoolAssignments).mockRejectedValue(
      new ApiError(403, 'This school_admin account is not linked to a school'),
    )
    renderPage()

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'This school_admin account is not linked to a school',
      ),
    )
  })
})
