import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Assignment, Crew, Driver, Qualification, Run, School, Vehicle } from '../api/types'
import { SchedulePage } from './SchedulePage'

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

function mockLoad() {
  vi.mocked(api.getRuns).mockResolvedValue([run])
  vi.mocked(api.getCrews).mockResolvedValue([crew, otherCrew])
  vi.mocked(api.getSchools).mockResolvedValue([school])
  vi.mocked(api.getDrivers).mockResolvedValue([driverRecord, otherDriver])
  vi.mocked(api.getVehicles).mockResolvedValue([vehicle, otherVehicle])
  vi.mocked(api.getQualifications).mockResolvedValue([vehicleQual])
  vi.mocked(api.getAssignments).mockResolvedValue([assignment])
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
})
