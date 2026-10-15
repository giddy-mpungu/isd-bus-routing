import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { CurrentUser, SchoolAssignment } from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { SchoolAdminPage } from './SchoolAdminPage'
import { axeViolations } from '../test/axe'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getCurrentUser: vi.fn(),
    getSchoolAssignments: vi.fn(),
    getSchoolBells: vi.fn(),
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

// Every state these tests reach is checked against WCAG 2.1 A/AA.
afterEach(async () => {
  expect(await axeViolations()).toEqual([])
})

describe('SchoolAdminPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([])
    vi.mocked(api.getSchoolBells).mockRejectedValue(new Error('not loaded in this test'))
  })

  it("shows the school's bell times and coming special days, read-only", async () => {
    vi.mocked(api.getSchoolAssignments).mockResolvedValue([])
    vi.mocked(api.getSchoolBells).mockResolvedValue({
      school_id: 1,
      school_name: 'Riverside Elementary',
      schedules: [
        {
          id: 10,
          school_id: 1,
          name: 'Regular',
          first_bell_minute: 480,
          dismissal_minute: 900,
          is_regular: true,
        },
      ],
      own_offsets: null,
      offsets_in_use: {
        arrive_earliest_before: 25,
        arrive_latest_before: 10,
        leave_earliest_after: 5,
        leave_latest_after: 15,
      },
      upcoming_days: [
        {
          id: 3,
          school_id: 1,
          school_name: 'Riverside Elementary',
          service_date: '2026-10-30',
          bell_schedule_id: 11,
          schedule_name: 'Early release',
        },
      ],
    })
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Bell schedule' })).toBeInTheDocument()
    expect(
      screen.getByText('Regular: first bell 08:00, dismissal 15:00 (regular)'),
    ).toBeInTheDocument()
    expect(screen.getByText('2026-10-30: Early release')).toBeInTheDocument()
    expect(api.getSchoolBells).toHaveBeenCalledWith(1)
    expect(screen.queryByRole('button', { name: /Edit/ })).not.toBeInTheDocument()
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

  it('shows when a bus is due at school and flags it running late', async () => {
    vi.mocked(api.getSchoolAssignments).mockResolvedValue([
      {
        ...assignment,
        planned_school_minute: 410,
        expected_school_minute: 421,
        delay_minutes: 11,
        running_late: true,
        eta_basis: 'Live GPS',
      },
      {
        ...assignment,
        id: 101,
        direction: 'pm',
        planned_school_minute: 900,
        expected_school_minute: 900,
        delay_minutes: 0,
        running_late: false,
        eta_basis: 'On plan',
      },
    ])
    renderPage()
    const late = await screen.findByText(/At school:/)
    expect(late).toHaveTextContent('At school: 07:01 (planned 06:50) Running 11 min late Live GPS')
    const onTime = screen.getByText(/Leaves school:/)
    expect(onTime).toHaveTextContent('Leaves school: 15:00 On plan')
    expect(onTime).not.toHaveTextContent('late')
  })
})
