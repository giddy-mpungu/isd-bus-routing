import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  Absence,
  AffectedAssignmentSubstitutes,
  Assignment,
  Crew,
  Driver,
  Qualification,
  Run,
  School,
  Vehicle,
} from '../api/types'
import { SchedulePage } from './SchedulePage'

// Matches SchedulePage's own today() default for `serviceDate` — the
// component doesn't use the fixtures' own service_date fields for
// that, so assertions on what date it actually passed to an API call
// need this, not a hardcoded string.
function today(): string {
  return new Date().toISOString().slice(0, 10)
}

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getRuns: vi.fn(),
    getCrews: vi.fn(),
    getSchools: vi.fn(),
    getDrivers: vi.fn(),
    getVehicles: vi.fn(),
    getQualifications: vi.fn(),
    getAssignments: vi.fn(),
    runSchedule: vi.fn(),
    updateAssignment: vi.fn(),
    deleteAssignment: vi.fn(),
    createCrew: vi.fn(),
    createRun: vi.fn(),
    getAbsencesForDate: vi.fn(),
    createAbsence: vi.fn(),
    getSubstituteCandidates: vi.fn(),
  }
})

const school: School = { id: 1, name: 'Riverside Elementary', location_lat: 0, location_lon: 0 }
const driverRecord: Driver = {
  id: 2,
  full_name: 'Jordan Driver',
  max_continuous_minutes: null,
  qualifications: [],
}
const vehicle: Vehicle = {
  id: 3,
  label: 'Bus 101',
  nominal_capacity: 48,
  effective_capacity: 44,
  qualifications: [],
}
const run: Run = {
  id: 10,
  service_date: '2026-09-01',
  school_id: 1,
  window_earliest: 360,
  window_latest: 410,
  duration_minutes: 40,
  buffer_minutes: 10,
  passenger_count: 12,
}
const crew: Crew = {
  id: 20,
  service_date: '2026-09-01',
  driver_id: 2,
  vehicle_id: 3,
  available_window_earliest: 0,
  available_window_latest: 1439,
}
const otherDriver: Driver = {
  id: 4,
  full_name: 'Sam Substitute',
  max_continuous_minutes: null,
  qualifications: [],
}
const otherVehicle: Vehicle = {
  id: 5,
  label: 'Bus 202',
  nominal_capacity: 48,
  effective_capacity: 44,
  qualifications: [],
}
const otherCrew: Crew = {
  id: 21,
  service_date: '2026-09-01',
  driver_id: 4,
  vehicle_id: 5,
  available_window_earliest: 0,
  available_window_latest: 1439,
}
const assignment: Assignment = {
  id: 100,
  run_id: 10,
  crew_id: 20,
  start_minute: 360,
  end_minute: 410,
  explanation_text: 'Crew 20 was assigned job 10 because qualifications are satisfied.',
  locked: false,
}

const vehicleQual: Qualification = {
  id: 1,
  code: 'lift',
  kind: 'vehicle_capability',
  description: 'Wheelchair lift',
}

const thirdDriver: Driver = {
  id: 6,
  full_name: 'Casey NoCrew',
  max_continuous_minutes: null,
  qualifications: [],
}

const absence: Absence = {
  id: 1,
  driver_id: 2,
  service_date: '2026-09-01',
  start_minute: 0,
  end_minute: 1439,
  reason: 'sick_leave',
}

function mockLoad() {
  vi.mocked(api.getRuns).mockResolvedValue([run])
  vi.mocked(api.getCrews).mockResolvedValue([crew, otherCrew])
  vi.mocked(api.getSchools).mockResolvedValue([school])
  vi.mocked(api.getDrivers).mockResolvedValue([driverRecord, otherDriver, thirdDriver])
  vi.mocked(api.getVehicles).mockResolvedValue([vehicle, otherVehicle])
  vi.mocked(api.getQualifications).mockResolvedValue([vehicleQual])
  vi.mocked(api.getAssignments).mockResolvedValue([assignment])
  vi.mocked(api.getAbsencesForDate).mockResolvedValue([absence])
}

describe('SchedulePage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockLoad()
  })

  it('renders the assignment row with joined school/window/crew names', async () => {
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const select = screen.getByRole('combobox', { name: 'Crew' })
    expect(select).toHaveValue(String(crew.id))
    expect(screen.getByRole('option', { name: 'Jordan Driver — Bus 101' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Sam Substitute — Bus 202' })).toBeInTheDocument()
  })

  it('reassigning the crew via the dropdown calls the API and reloads', async () => {
    vi.mocked(api.updateAssignment).mockResolvedValue({ ...assignment, crew_id: otherCrew.id })
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const select = screen.getByRole('combobox', { name: 'Crew' })
    expect(select).toHaveValue(String(crew.id))

    const user = userEvent.setup()
    await user.selectOptions(select, String(otherCrew.id))

    await waitFor(() =>
      expect(api.updateAssignment).toHaveBeenCalledWith(100, { crew_id: otherCrew.id }),
    )
    expect(api.getAssignments).toHaveBeenCalledTimes(2) // initial load + reload after PATCH
  })

  it('shows the rejection reason and leaves the crew unchanged when reassignment is invalid', async () => {
    vi.mocked(api.updateAssignment).mockRejectedValue(
      new ApiError(422, "Crew 21's vehicle is missing required qualification(s): ['lift']"),
    )
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const select = screen.getByRole('combobox', { name: 'Crew' })
    const user = userEvent.setup()
    await user.selectOptions(select, String(otherCrew.id))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('missing required qualification'),
    )
    // assignments state was never updated, so the control still shows
    // the original (unchanged) crew rather than the rejected one.
    expect(select).toHaveValue(String(crew.id))
  })

  it('locking an assignment calls the API with the toggled state and reloads', async () => {
    vi.mocked(api.updateAssignment).mockResolvedValue({ ...assignment, locked: true })
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /^lock$/i }))

    await waitFor(() => expect(api.updateAssignment).toHaveBeenCalledWith(100, { locked: true }))
    expect(api.getAssignments).toHaveBeenCalledTimes(2) // initial load + reload after PATCH
  })

  it('running the schedule shows the infeasible reason returned by the API on failure', async () => {
    vi.mocked(api.runSchedule).mockRejectedValue(new ApiError(422, 'No crews supplied'))
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /run schedule/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No crews supplied'))
  })

  it('creating a crew calls the API with the selected driver/vehicle and reloads', async () => {
    vi.mocked(api.createCrew).mockResolvedValue({ ...crew, id: 99 })
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Driver'), String(driverRecord.id))
    await user.selectOptions(screen.getByLabelText('Vehicle'), String(vehicle.id))
    await user.click(screen.getByRole('button', { name: 'Add crew' }))

    await waitFor(() =>
      expect(api.createCrew).toHaveBeenCalledWith(
        expect.objectContaining({
          driver_id: driverRecord.id,
          vehicle_id: vehicle.id,
          available_window_earliest: 0,
          available_window_latest: 1439,
        }),
      ),
    )
    expect(api.getCrews).toHaveBeenCalledTimes(2) // initial load + reload after create
  })

  it('creating a run sends the selected school, window, and required qualifications', async () => {
    vi.mocked(api.createRun).mockResolvedValue({ ...run, id: 99 })
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('School'), String(school.id))
    await user.type(screen.getByLabelText('Window start (minute of day)'), '480')
    await user.type(screen.getByLabelText('Window end (minute of day)'), '540')
    await user.type(screen.getByLabelText('Duration (minutes)'), '45')
    await user.click(screen.getByRole('checkbox', { name: /lift/ }))
    await user.click(screen.getByRole('button', { name: 'Add run' }))

    await waitFor(() =>
      expect(api.createRun).toHaveBeenCalledWith(
        expect.objectContaining({
          school_id: school.id,
          window_earliest: 480,
          window_latest: 540,
          duration_minutes: 45,
          required_qualification_codes: ['lift'],
        }),
      ),
    )
    expect(api.getRuns).toHaveBeenCalledTimes(2) // initial load + reload after create
  })

  it('shows the server error message when creating a run fails validation', async () => {
    vi.mocked(api.createRun).mockRejectedValue(
      new ApiError(400, "duration_minutes + buffer_minutes exceeds the run's own window length"),
    )
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('School'), String(school.id))
    await user.type(screen.getByLabelText('Window start (minute of day)'), '480')
    await user.type(screen.getByLabelText('Window end (minute of day)'), '500')
    await user.type(screen.getByLabelText('Duration (minutes)'), '45')
    await user.click(screen.getByRole('button', { name: 'Add run' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/exceeds the run/))
  })

  it('renders a reported absence with the driver name resolved', async () => {
    render(<SchedulePage />)
    const findButton = await screen.findByRole('button', { name: 'Find substitutes' })
    const row = findButton.closest('li')
    expect(row).toHaveTextContent('Jordan Driver')
    expect(row).toHaveTextContent('sick leave')
  })

  it('finding substitutes shows the ranked candidate panel', async () => {
    const affected: AffectedAssignmentSubstitutes = {
      assignment_id: 100,
      run_id: 10,
      school_name: 'Riverside Elementary',
      start_minute: 360,
      end_minute: 410,
      vehicle_id: 3,
      vehicle_label: 'Bus 101',
      candidates: [
        {
          driver_id: 4,
          full_name: 'Sam Substitute',
          score: 2,
          reasons: ['has driven this school 2 time(s) before'],
        },
      ],
    }
    vi.mocked(api.getSubstituteCandidates).mockResolvedValue([affected])
    render(<SchedulePage />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Find substitutes' })).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Find substitutes' }))

    await waitFor(() => expect(api.getSubstituteCandidates).toHaveBeenCalledWith(2, today()))
    const panel = (await screen.findByRole('heading', { level: 3 })).closest('div') as HTMLElement
    expect(within(panel).getByText(/Sam Substitute/)).toBeInTheDocument()
    expect(within(panel).getByText(/Bus 101/)).toBeInTheDocument()
  })

  it('assigning a substitute who already has a crew that day reassigns directly, without creating a new crew', async () => {
    const affected: AffectedAssignmentSubstitutes = {
      assignment_id: 100,
      run_id: 10,
      school_name: 'Riverside Elementary',
      start_minute: 360,
      end_minute: 410,
      vehicle_id: 3,
      vehicle_label: 'Bus 101',
      candidates: [{ driver_id: 4, full_name: 'Sam Substitute', score: 1, reasons: ['available'] }],
    }
    vi.mocked(api.getSubstituteCandidates).mockResolvedValue([affected])
    vi.mocked(api.updateAssignment).mockResolvedValue({ ...assignment, crew_id: otherCrew.id })
    render(<SchedulePage />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Find substitutes' })).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Find substitutes' }))
    await screen.findByRole('button', { name: 'Assign as substitute' })
    await user.click(screen.getByRole('button', { name: 'Assign as substitute' }))

    await waitFor(() =>
      expect(api.updateAssignment).toHaveBeenCalledWith(100, { crew_id: otherCrew.id }),
    )
    expect(api.createCrew).not.toHaveBeenCalled()
  })

  it('assigning a substitute with no existing crew that day creates one first', async () => {
    const affected: AffectedAssignmentSubstitutes = {
      assignment_id: 100,
      run_id: 10,
      school_name: 'Riverside Elementary',
      start_minute: 360,
      end_minute: 410,
      vehicle_id: 3,
      vehicle_label: 'Bus 101',
      candidates: [{ driver_id: 6, full_name: 'Casey NoCrew', score: 0, reasons: ['available'] }],
    }
    const newCrew: Crew = {
      id: 99,
      service_date: '2026-09-01',
      driver_id: 6,
      vehicle_id: 3,
      available_window_earliest: 0,
      available_window_latest: 1439,
    }
    vi.mocked(api.getSubstituteCandidates).mockResolvedValue([affected])
    vi.mocked(api.createCrew).mockResolvedValue(newCrew)
    vi.mocked(api.updateAssignment).mockResolvedValue({ ...assignment, crew_id: newCrew.id })
    render(<SchedulePage />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Find substitutes' })).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Find substitutes' }))
    await screen.findByRole('button', { name: 'Assign as substitute' })
    await user.click(screen.getByRole('button', { name: 'Assign as substitute' }))

    await waitFor(() =>
      expect(api.createCrew).toHaveBeenCalledWith({
        service_date: today(),
        driver_id: 6,
        vehicle_id: 3,
        available_window_earliest: 0,
        available_window_latest: 1439,
      }),
    )
    expect(api.updateAssignment).toHaveBeenCalledWith(100, { crew_id: 99 })
  })

  it('reporting an absence with the whole-day default submits 0/1439', async () => {
    vi.mocked(api.createAbsence).mockResolvedValue(absence)
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Absent driver'), String(driverRecord.id))
    await user.click(screen.getByRole('button', { name: 'Report absence' }))

    await waitFor(() =>
      expect(api.createAbsence).toHaveBeenCalledWith(
        driverRecord.id,
        expect.objectContaining({
          service_date: today(),
          start_minute: 0,
          end_minute: 1439,
          reason: 'sick_leave',
        }),
      ),
    )
  })
})
