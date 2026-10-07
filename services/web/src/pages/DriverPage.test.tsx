import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  Absence,
  CurrentUser,
  DriverAssignment,
  DriverDispatchTask,
  DriverFieldTrip,
} from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { DriverPage } from './DriverPage'
import { currentLanguage } from '../i18n'
import { stubGeolocation } from '../test/geolocation'
import { axeViolations } from '../test/axe'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getCurrentUser: vi.fn(),
    getMyAssignments: vi.fn(),
    markAssignmentsReceived: vi.fn(),
    getMyDispatchTasks: vi.fn(),
    markDispatchTasksReceived: vi.fn(),
    updateDispatchTaskStatus: vi.fn(),
    getMyFieldTrips: vi.fn(),
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
  status: 'received',
  locked: false,
  roster_ambiguous: false,
  stops: [],
}

function renderPage() {
  vi.mocked(api.getCurrentUser).mockResolvedValue(driverUser)
  return render(
    <AuthProvider>
      <DriverPage />
    </AuthProvider>,
  )
}

// Every state these tests reach is checked against WCAG 2.1 A/AA.
afterEach(async () => {
  expect(await axeViolations()).toEqual([])
})

describe('DriverPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([])
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([])
    vi.mocked(api.getMyFieldTrips).mockResolvedValue([])
    vi.mocked(api.markAssignmentsReceived).mockImplementation(async () => [
      { ...assignment, status: 'received' },
    ])
  })

  it('renders messages from dispatch when there are announcements for drivers', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([
      {
        id: 1,
        message: 'Route 12 substitute driver today.',
        category: 'substitution',
        audience: 'driver',
        school_id: null,
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
    expect(screen.getByText('Received')).toBeInTheDocument()
  })

  it("shows the run in the driver's chosen language", async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.getCurrentUser).mockResolvedValue({ ...driverUser, preferred_language: 'es' })
    render(
      <AuthProvider>
        <DriverPage />
      </AuthProvider>,
    )

    expect(await screen.findByText('Vehículo: Bus 101')).toBeInTheDocument()
    expect(currentLanguage()).toBe('es')
    expect(screen.getByText('Recibida')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirmar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Leer en voz alta' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Informar una ausencia' })).toBeInTheDocument()
  })

  it('shows expected riders grouped by stop, and notes it is not a route order', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([
      {
        ...assignment,
        stops: [
          { stop_label: 'Elm St', student_names: ['Ana', 'Ben'] },
          { stop_label: null, student_names: ['Cy'] },
        ],
      },
    ])
    renderPage()

    await waitFor(() => expect(screen.getByText(/Elm St/)).toBeInTheDocument())
    expect(screen.getByText('Elm St: Ana, Ben')).toBeInTheDocument()
    expect(screen.getByText('No stop assigned: Cy')).toBeInTheDocument()
    expect(screen.getByText(/this run's route has no stop list yet/)).toBeInTheDocument()
  })

  it('warns about a road closure near the route', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([
      {
        ...assignment,
        stops_ordered: true,
        closure_notes: ['flooding: Underpass flooded (the Near stop is inside it)'],
        stops: [
          {
            stop_label: 'Near',
            student_names: ['Cy'],
            position: 1,
            planned_minute: 420,
            eta_minute: 420,
            skipped: false,
            on_route: true,
          },
        ],
      },
    ])
    renderPage()
    const notice = await screen.findByText('Road closure near your route.')
    expect(notice.closest('.driver-closure')).toHaveTextContent(
      'flooding: Underpass flooded (the Near stop is inside it)',
    )
  })

  it("shows today's times, the planned time when it moved, and skipped stops", async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([
      {
        ...assignment,
        stops_ordered: true,
        stops: [
          {
            stop_label: 'Far',
            student_names: ['Ana'],
            position: 1,
            planned_minute: 420,
            eta_minute: 428,
            skipped: false,
            on_route: true,
          },
          {
            stop_label: 'Mid',
            student_names: [],
            position: 2,
            planned_minute: 430,
            eta_minute: null,
            skipped: true,
            on_route: true,
          },
          {
            stop_label: 'Near',
            student_names: ['Cy'],
            position: 3,
            planned_minute: 436,
            eta_minute: 436,
            skipped: false,
            on_route: true,
          },
        ],
      },
    ])
    renderPage()
    await screen.findByRole('heading', { name: 'Stops in order' })
    const items = Array.from(document.querySelectorAll('.driver-route-stops li'))
    expect(items.map((li) => li.textContent)).toEqual([
      '07:08 Far: Ana (planned 07:00)',
      'Mid: skip, nobody riding today',
      '07:16 Near: Cy',
    ])
    expect(items[1]).toHaveClass('is-skipped')
  })

  it("lists the route's stops in order with planned times", async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([
      {
        ...assignment,
        stops_ordered: true,
        stops: [
          {
            stop_label: 'Elm St',
            student_names: ['Ben', 'Cy'],
            position: 1,
            planned_minute: 360,
            on_route: true,
          },
          {
            stop_label: 'Oak St',
            student_names: [],
            position: 2,
            planned_minute: null,
            on_route: true,
          },
          {
            stop_label: 'Maple',
            student_names: ['Dee'],
            position: null,
            planned_minute: null,
            on_route: false,
          },
        ],
      },
    ])
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Stops in order' })).toBeInTheDocument()
    const items = Array.from(document.querySelectorAll('.driver-route-stops li')).map(
      (li) => li.textContent,
    )
    expect(items).toEqual(['06:00 Elm St: Ben, Cy', 'Oak St: nobody expected today'])
    expect(screen.getByText(/Also expected, at stops not on this route/)).toBeInTheDocument()
    expect(screen.getByText('Maple: Dee')).toBeInTheDocument()
    expect(screen.queryByText(/Not a route order/)).not.toBeInTheDocument()
  })

  it('shows an ambiguous note instead of a roster when more than one bus serves the school', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([
      { ...assignment, roster_ambiguous: true, stops: [] },
    ])
    renderPage()

    await waitFor(() =>
      expect(screen.getByText(/more than one bus serves this school today/)).toBeInTheDocument(),
    )
  })

  it('shows a no-riders message when nobody is expected', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment]) // stops: []
    renderPage()

    await waitFor(() => expect(screen.getByText('No riders expected today.')).toBeInTheDocument())
  })

  it('shows a friendly message when there are no runs today', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([])
    renderPage()

    await waitFor(() =>
      expect(screen.getByText('Nothing scheduled for you today.')).toBeInTheDocument(),
    )
  })

  it('marks newly sent work as received when the tablet loads it', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: 'sent' }])
    renderPage()
    await waitFor(() => expect(api.markAssignmentsReceived).toHaveBeenCalledWith(today()))
    expect(await screen.findByText('Received')).toBeInTheDocument()
  })

  it('does not call receipt when nothing new was sent', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    renderPage()
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())
    expect(api.markAssignmentsReceived).not.toHaveBeenCalled()
  })

  it.each([
    ['received', 'Acknowledge', 'acknowledged'],
    ['acknowledged', "I'm en route", 'en_route'],
    ['en_route', 'Arrived', 'arrived'],
    ['arrived', 'Start run', 'in_progress'],
    ['in_progress', 'Complete run', 'completed'],
  ] as const)('from %s, the one next step is "%s"', async (from, label, to) => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: from }])
    vi.mocked(api.updateAssignmentStatus).mockResolvedValue({ ...assignment, status: to })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: label }))

    await waitFor(() => expect(api.updateAssignmentStatus).toHaveBeenCalledWith(100, to))
    expect(api.getMyAssignments).toHaveBeenCalledTimes(2) // initial load + reload after PATCH
  })

  it('offers no further step or no-show once a run is finished', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: 'completed' }])
    renderPage()
    await waitFor(() => expect(screen.getByText('Completed')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'No-show' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Complete run' })).not.toBeInTheDocument()
  })

  it('no-show is available until the run is finished', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: 'acknowledged' }])
    vi.mocked(api.updateAssignmentStatus).mockResolvedValue({ ...assignment, status: 'no_show' })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'No-show' }))
    await waitFor(() => expect(api.updateAssignmentStatus).toHaveBeenCalledWith(100, 'no_show'))
  })

  it('shows an error message when the status update fails', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.updateAssignmentStatus).mockRejectedValue(new ApiError(403, 'Not your run'))
    renderPage()
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Acknowledge' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Not your run'))
  })

  it('reports position automatically (ADR 0009) when a run is in progress', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: 'in_progress' }])
    vi.mocked(api.reportPosition).mockResolvedValue(undefined)
    const watchPosition = vi.fn((success: PositionCallback) => {
      success({
        coords: { latitude: 29.71, longitude: -95.41, speed: null } as GeolocationCoordinates,
        timestamp: 1_700_000_000_000,
      } as GeolocationPosition)
      return 1
    })
    stubGeolocation({ watchPosition, clearWatch: vi.fn() })

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

  it('does not report position before the bus is under way', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: 'acknowledged' }])
    const watchPosition = vi.fn()
    stubGeolocation({ watchPosition, clearWatch: vi.fn() })

    renderPage()
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())

    expect(watchPosition).not.toHaveBeenCalled()
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
      expect(screen.getByText('Nothing scheduled for you today.')).toBeInTheDocument(),
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
      expect(screen.getByText('Nothing scheduled for you today.')).toBeInTheDocument(),
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
      expect(screen.getByText('Nothing scheduled for you today.')).toBeInTheDocument(),
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
      expect(screen.getByText('Nothing scheduled for you today.')).toBeInTheDocument(),
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
      expect(screen.getByText('Nothing scheduled for you today.')).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Description'), 'Something happened.')
    await user.click(screen.getByRole('button', { name: 'Submit report' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Not linked'))
  })
})

const task: DriverDispatchTask = {
  id: 7,
  kind: 'assist_disabled_bus',
  service_date: today(),
  start_minute: 540,
  end_minute: 600,
  vehicle_label: 'Bus 30',
  location: 'Oak St & 5th Ave',
  instructions: 'Bus 12 is down. Pick up its riders.',
  status: 'received',
  cancelled: false,
}

const trip: DriverFieldTrip = {
  id: 5,
  status: 'assigned',
  requesting_party: 'Riverside 5th grade',
  origin: 'Riverside Elementary',
  destination: 'Science Museum',
  departure_at: `${today()}T12:00:00`,
  return_at: `${today()}T15:30:00`,
  start_minute: 720,
  end_minute: 930,
  passenger_count: 30,
  vehicle_label: 'Bus 101',
  bus_assistant_name: null,
  trip_contact: 'Ms. Patel',
  special_instructions: 'Two students use wheelchairs.',
  destination_profile: {
    id: 1,
    name: 'Science Museum',
    location_lat: null,
    location_lon: null,
    approved_entrance: 'North gate on Elm St',
    parking_notes: null,
    turn_restrictions: null,
    driver_notes: null,
    created_at: '2026-01-01T00:00:00Z',
  },
}

function cardTitles(): string[] {
  return Array.from(document.querySelectorAll('.driver-run-school')).map(
    (el) => el.textContent ?? '',
  )
}

function slotLabels(): string[] {
  return Array.from(document.querySelectorAll('.driver-queue-slot')).map(
    (el) => el.textContent ?? '',
  )
}

describe('DriverPage: the day as one queue (spec sections 11 and 14)', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([])
    vi.mocked(api.getMyAssignments).mockResolvedValue([])
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([])
    vi.mocked(api.getMyFieldTrips).mockResolvedValue([])
  })

  it('shows runs, field trips and dispatch tasks in time order as current, next and later', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment]) // 06:00
    vi.mocked(api.getMyFieldTrips).mockResolvedValue([trip]) // 12:00
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([task]) // 09:00
    renderPage()

    await waitFor(() => expect(cardTitles()).toHaveLength(3))
    expect(cardTitles()).toEqual([
      'Riverside Elementary',
      'Dispatch: Assist a disabled bus',
      'Field trip #5 to Science Museum',
    ])
    expect(slotLabels()).toEqual(['Current', 'Next', 'Later'])
    expect(screen.getByText('Where: Oak St & 5th Ave')).toBeInTheDocument()
    expect(screen.getByText('Bus 12 is down. Pick up its riders.')).toBeInTheDocument()
    expect(screen.getByText('Approved entrance: North gate on Elm St')).toBeInTheDocument()
    expect(screen.getByText('Two students use wheelchairs.')).toBeInTheDocument()
  })

  it('makes work already under way current, and marks finished work done', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: 'acknowledged' }])
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([
      { ...task, id: 8, start_minute: 300, end_minute: 330, status: 'completed' },
      { ...task, status: 'en_route' },
    ])
    vi.mocked(api.getMyFieldTrips).mockResolvedValue([trip])
    renderPage()

    await waitFor(() => expect(cardTitles()).toHaveLength(4))
    // 05:00 task (done), 06:00 run, 09:00 task (under way), 12:00 trip.
    expect(slotLabels()).toEqual(['Done', 'Next', 'Current', 'Later'])
  })

  it('marks a newly sent task as received when the tablet loads it', async () => {
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([{ ...task, status: 'sent' }])
    vi.mocked(api.markDispatchTasksReceived).mockResolvedValue([task])
    renderPage()

    await waitFor(() => expect(api.markDispatchTasksReceived).toHaveBeenCalledWith(today()))
    expect(await screen.findByText('Received')).toBeInTheDocument()
    expect(api.markAssignmentsReceived).not.toHaveBeenCalled()
  })

  it.each([
    ['received', 'Acknowledge', 'acknowledged'],
    ['acknowledged', "I'm en route", 'en_route'],
    ['arrived', 'Start task', 'in_progress'],
    ['in_progress', 'Task done', 'completed'],
  ] as const)('a task from %s moves on with "%s"', async (from, label, to) => {
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([{ ...task, status: from }])
    vi.mocked(api.updateDispatchTaskStatus).mockResolvedValue({ ...task, status: to })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: label }))

    await waitFor(() => expect(api.updateDispatchTaskStatus).toHaveBeenCalledWith(7, to))
    expect(api.updateAssignmentStatus).not.toHaveBeenCalled()
    expect(api.getMyDispatchTasks).toHaveBeenCalledTimes(2) // initial load + reload
  })

  it('shows a task dispatch cancelled, with nothing to tap', async () => {
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([
      { ...task, status: 'sent', cancelled: true },
    ])
    renderPage()

    expect(await screen.findByText('Cancelled by dispatch')).toBeInTheDocument()
    expect(slotLabels()).toEqual(['Cancelled'])
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument()
    expect(api.markDispatchTasksReceived).not.toHaveBeenCalled()
  })

  it('shows a task update error from the server', async () => {
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([task])
    vi.mocked(api.updateDispatchTaskStatus).mockRejectedValue(
      new ApiError(409, 'Dispatch cancelled this task.'),
    )
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Acknowledge' }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Dispatch cancelled this task.'),
    )
  })

  it('reports position while a dispatch task is under way', async () => {
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([{ ...task, status: 'en_route' }])
    vi.mocked(api.reportPosition).mockResolvedValue(undefined)
    const watchPosition = vi.fn((success: PositionCallback) => {
      success({
        coords: { latitude: 29.71, longitude: -95.41, speed: null } as GeolocationCoordinates,
        timestamp: 1_700_000_000_000,
      } as GeolocationPosition)
      return 1
    })
    stubGeolocation({ watchPosition, clearWatch: vi.fn() })

    renderPage()

    await waitFor(() =>
      expect(api.reportPosition).toHaveBeenCalledWith(
        100,
        expect.objectContaining({ location_lat: 29.71, location_lon: -95.41 }),
      ),
    )
    vi.unstubAllGlobals()
  })
})

// A GPS the test drives: send(speed in m/s, seconds since start).
function fakeGps() {
  let onFix: PositionCallback | null = null
  let onError: PositionErrorCallback | null = null
  const clearWatch = vi.fn()
  const watchPosition = vi.fn((success: PositionCallback, error?: PositionErrorCallback | null) => {
    onFix = success
    onError = error ?? null
    return 7
  })
  stubGeolocation({ watchPosition, clearWatch })
  return {
    watchPosition,
    clearWatch,
    send(speed: number | null, seconds: number) {
      act(() =>
        onFix!({
          coords: { latitude: 29.71, longitude: -95.41, speed } as GeolocationCoordinates,
          timestamp: 1_700_000_000_000 + seconds * 1000,
        } as GeolocationPosition),
      )
    },
    fail() {
      act(() => onError!({ code: 2, message: 'no signal' } as GeolocationPositionError))
    },
  }
}

describe('DriverPage: locked while the bus is moving (spec section 9)', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([])
    vi.mocked(api.getMyDispatchTasks).mockResolvedValue([])
    vi.mocked(api.getMyFieldTrips).mockResolvedValue([])
    vi.mocked(api.reportPosition).mockResolvedValue(undefined)
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: 'en_route' }])
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function renderUnderway() {
    const gps = fakeGps()
    renderPage()
    await waitFor(() => expect(gps.watchPosition).toHaveBeenCalled())
    return gps
  }

  it('locks typing and no-show while moving, but keeps the next step', async () => {
    const gps = await renderUnderway()
    gps.send(12, 0) // about 27 mph

    expect(screen.getByRole('status')).toHaveTextContent('Bus moving: typing is locked')
    expect(screen.getByLabelText('Description')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Submit report' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Report absence' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'No-show' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Arrived' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Read aloud' })).toBeEnabled()
  })

  it('stays locked at a crawl and unlocks once stopped', async () => {
    const gps = await renderUnderway()
    gps.send(12, 0)
    gps.send(1.5, 5) // crawling in traffic
    expect(screen.getByRole('button', { name: 'Submit report' })).toBeDisabled()
    gps.send(0.3, 10)
    expect(screen.queryByText(/Bus moving/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Submit report' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'No-show' })).toBeEnabled()
  })

  it('stays unlocked below walking-pace speeds', async () => {
    const gps = await renderUnderway()
    gps.send(2, 0)
    expect(screen.queryByText(/Bus moving/)).not.toBeInTheDocument()
  })

  it('unlocks when GPS is lost, since it can no longer tell', async () => {
    const gps = await renderUnderway()
    gps.send(12, 0)
    gps.fail()
    expect(screen.queryByText(/Bus moving/)).not.toBeInTheDocument()
  })

  it('reports the position at most every 20 seconds', async () => {
    const gps = await renderUnderway()
    for (const second of [0, 5, 10, 15, 20, 25]) gps.send(10, second)
    expect(api.reportPosition).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.reportPosition).mock.calls[1][1].recorded_at).toBe(
      new Date(1_700_000_020_000).toISOString(),
    )
  })

  it('stops watching the GPS once nothing is under way', async () => {
    const gps = await renderUnderway()
    vi.mocked(api.getMyAssignments).mockResolvedValue([{ ...assignment, status: 'completed' }])
    vi.mocked(api.updateAssignmentStatus).mockResolvedValue({ ...assignment, status: 'arrived' })
    gps.send(0, 0)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Arrived' }))
    await waitFor(() => expect(gps.clearWatch).toHaveBeenCalledWith(7))
  })
})
