import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Absence, CurrentUser, DriverAssignment } from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { DriverPage } from './DriverPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getCurrentUser: vi.fn(),
    getMyAssignments: vi.fn(),
    updateAssignmentStatus: vi.fn(),
    createAbsence: vi.fn(),
    reportPosition: vi.fn(),
    getMyAnnouncements: vi.fn(),
    createDriverReport: vi.fn(),
  }
})

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

const driverUser: CurrentUser = {
  id: 1,
  email: 'driver@example.org',
  full_name: 'Jordan Driver',
  role: 'driver',
  is_active: true,
  driver_id: 100,
  school_id: null,
  student_id: null,
}

const assignment: DriverAssignment = {
  id: 100,
  run_id: 10,
  service_date: today(),
  school_name: 'Riverside Elementary',
  vehicle_label: 'Bus 101',
  start_minute: 360,
  end_minute: 410,
  status: 'scheduled',
  locked: false,
}

function renderPage() {
  vi.mocked(api.getCurrentUser).mockResolvedValue(driverUser)
  return render(
    <AuthProvider>
      <DriverPage />
    </AuthProvider>,
  )
}

describe('DriverPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([])
  })

  it('renders messages from dispatch when there are announcements for drivers', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([
      {
        id: 1,
        message: 'Route 12 substitute driver today.',
        category: 'substitution',
        audience: 'driver',
        created_at: '2026-09-14T12:00:00Z',
      },
    ])
    renderPage()

    await waitFor(() =>
      expect(screen.getByText(/Route 12 substitute driver today\./)).toBeInTheDocument(),
    )
  })

  it('renders a run card with resolved school/vehicle names and time window', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    renderPage()

    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())
    expect(screen.getByText('Vehicle: Bus 101')).toBeInTheDocument()
    expect(screen.getByText('06:00 – 06:50')).toBeInTheDocument()
    expect(screen.getByText('Status: Not started')).toBeInTheDocument()
  })

  it('shows a friendly message when there are no runs today', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([])
    renderPage()

    await waitFor(() =>
      expect(screen.getByText('No runs scheduled for today.')).toBeInTheDocument(),
    )
  })

  it('tapping Start calls the status PATCH and refreshes the card', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.updateAssignmentStatus).mockResolvedValue({
      ...assignment,
      status: 'in_progress',
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Start' }))

    await waitFor(() => expect(api.updateAssignmentStatus).toHaveBeenCalledWith(100, 'in_progress'))
    expect(api.getMyAssignments).toHaveBeenCalledTimes(2) // initial load + reload after PATCH
  })

  it('tapping Complete calls the status PATCH with completed', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.updateAssignmentStatus).mockResolvedValue({ ...assignment, status: 'completed' })
    renderPage()
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Complete' }))

    await waitFor(() => expect(api.updateAssignmentStatus).toHaveBeenCalledWith(100, 'completed'))
  })

  it('shows an error message when the status update fails', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.updateAssignmentStatus).mockRejectedValue(new ApiError(403, 'Not your run'))
    renderPage()
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Start' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Not your run'))
  })

  it('reports position automatically (ADR 0009) when a run is in progress', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: 'in_progress' }])
    vi.mocked(api.reportPosition).mockResolvedValue(undefined)
    const getCurrentPosition = vi.fn((success: PositionCallback) => {
      success({
        coords: { latitude: 29.71, longitude: -95.41 } as GeolocationCoordinates,
        timestamp: 1_700_000_000_000,
      } as GeolocationPosition)
    })
    vi.stubGlobal('navigator', { ...navigator, geolocation: { getCurrentPosition } })

    renderPage()

    await waitFor(() =>
      expect(api.reportPosition).toHaveBeenCalledWith(
        100,
        expect.objectContaining({
          service_date: today(),
          location_lat: 29.71,
          location_lon: -95.41,
        }),
      ),
    )
    vi.unstubAllGlobals()
  })

  it('does not report position when no run is in progress', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment]) // status: 'scheduled'
    const getCurrentPosition = vi.fn()
    vi.stubGlobal('navigator', { ...navigator, geolocation: { getCurrentPosition } })

    renderPage()
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())

    expect(getCurrentPosition).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it("reporting a whole-day absence calls createAbsence with the driver's own id", async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([])
    const created: Absence = {
      id: 5,
      driver_id: 100,
      service_date: today(),
      start_minute: 0,
      end_minute: 1439,
      reason: 'sick_leave',
    }
    vi.mocked(api.createAbsence).mockResolvedValue(created)
    renderPage()
    await waitFor(() =>
      expect(screen.getByText('No runs scheduled for today.')).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Report absence' }))

    await waitFor(() =>
      expect(api.createAbsence).toHaveBeenCalledWith(100, {
        service_date: today(),
        start_minute: 0,
        end_minute: 1439,
        reason: 'sick_leave',
      }),
    )
    await waitFor(() => expect(screen.getByText('Absence reported.')).toBeInTheDocument())
  })

  it('unchecking whole day sends the entered start/end minutes', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([])
    vi.mocked(api.createAbsence).mockResolvedValue({
      id: 6,
      driver_id: 100,
      service_date: today(),
      start_minute: 480,
      end_minute: 600,
      reason: 'personal_day',
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByText('No runs scheduled for today.')).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Reason'), 'personal_day')
    await user.click(screen.getByLabelText('Whole day'))
    await user.clear(screen.getByLabelText('Start (minute of day)'))
    await user.type(screen.getByLabelText('Start (minute of day)'), '480')
    await user.clear(screen.getByLabelText('End (minute of day)'))
    await user.type(screen.getByLabelText('End (minute of day)'), '600')
    await user.click(screen.getByRole('button', { name: 'Report absence' }))

    await waitFor(() =>
      expect(api.createAbsence).toHaveBeenCalledWith(100, {
        service_date: today(),
        start_minute: 480,
        end_minute: 600,
        reason: 'personal_day',
      }),
    )
  })

  it('shows an error message when reporting an absence fails', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([])
    vi.mocked(api.createAbsence).mockRejectedValue(
      new ApiError(400, 'start_minute must be <= end_minute'),
    )
    renderPage()
    await waitFor(() =>
      expect(screen.getByText('No runs scheduled for today.')).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Report absence' }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('start_minute must be <= end_minute'),
    )
  })

  it("submitting a vehicle defect report calls createDriverReport with the driver's own id", async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([])
    vi.mocked(api.createDriverReport).mockResolvedValue({
      id: 1,
      driver_id: 100,
      vehicle_id: 5,
      service_date: today(),
      report_type: 'vehicle_defect',
      description: 'Brake pedal feels soft.',
      created_at: today(),
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByText('No runs scheduled for today.')).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Type'), 'vehicle_defect')
    await user.type(screen.getByLabelText('Description'), 'Brake pedal feels soft.')
    await user.click(screen.getByRole('button', { name: 'Submit report' }))

    await waitFor(() =>
      expect(api.createDriverReport).toHaveBeenCalledWith(100, {
        service_date: today(),
        report_type: 'vehicle_defect',
        description: 'Brake pedal feels soft.',
      }),
    )
    await waitFor(() => expect(screen.getByText('Report submitted.')).toBeInTheDocument())
  })

  it('shows an error message when submitting a report fails', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([])
    vi.mocked(api.createDriverReport).mockRejectedValue(new ApiError(403, 'Not linked'))
    renderPage()
    await waitFor(() =>
      expect(screen.getByText('No runs scheduled for today.')).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Description'), 'Something happened.')
    await user.click(screen.getByRole('button', { name: 'Submit report' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Not linked'))
  })
})
