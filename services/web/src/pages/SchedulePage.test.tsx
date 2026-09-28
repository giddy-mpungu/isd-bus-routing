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
  VehiclePosition,
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
    generateFromTemplates: vi.fn(),
    updateAssignment: vi.fn(),
    deleteAssignment: vi.fn(),
    createCrew: vi.fn(),
    updateCrewDriver: vi.fn(),
    createRun: vi.fn(),
    updateRun: vi.fn(),
    getExpectedRiders: vi.fn(),
    getAbsencesForDate: vi.fn(),
    createAbsence: vi.fn(),
    getSubstituteCandidates: vi.fn(),
    getFleetPositions: vi.fn(),
    getObservedRunDuration: vi.fn(),
    getDriverReportsForDate: vi.fn(),
    getDispatchTasks: vi.fn(),
    getAlerts: vi.fn(),
    getCrewTrack: vi.fn(),
  }
})

const school: School = { id: 1, name: 'Riverside Elementary', location_lat: 0, location_lon: 0 }
const driverRecord: Driver = {
  id: 2,
  full_name: 'Jordan Driver',
  max_continuous_minutes: null,
  license_class: 'cdl_b',
  is_active: true,
  qualifications: [],
}
const vehicle: Vehicle = {
  id: 3,
  label: 'Bus 101',
  nominal_capacity: 48,
  effective_capacity: 44,
  length_m: null,
  width_m: null,
  height_m: null,
  weight_kg: null,
  required_license_class: 'cdl_b',
  is_active: true,
  qualifications: [],
}
const run: Run = {
  id: 10,
  service_date: '2026-09-01',
  school_id: 1,
  direction: 'am',
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
  license_class: 'cdl_b',
  is_active: true,
  qualifications: [],
}
const otherVehicle: Vehicle = {
  id: 5,
  label: 'Bus 202',
  nominal_capacity: 48,
  effective_capacity: 44,
  length_m: null,
  width_m: null,
  height_m: null,
  weight_kg: null,
  required_license_class: 'cdl_b',
  is_active: true,
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
  status: 'sent',
  availability_issue: null,
}

const vehicleQual: Qualification = {
  id: 1,
  code: 'lift',
  kind: 'vehicle_capability',
  description: 'Wheelchair lift',
  is_active: true,
}

const thirdDriver: Driver = {
  id: 6,
  full_name: 'Casey NoCrew',
  max_continuous_minutes: null,
  license_class: 'cdl_b',
  is_active: true,
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
  vi.mocked(api.getFleetPositions).mockResolvedValue([])
  vi.mocked(api.getDriverReportsForDate).mockResolvedValue([])
  vi.mocked(api.getDispatchTasks).mockResolvedValue([])
  vi.mocked(api.getAlerts).mockResolvedValue({
    service_date: '2026-01-01',
    district_time: null,
    alerts: [],
  })
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

  it('reports deadhead and buffer totals after solving, and omits them when nothing was solved', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runSchedule).mockResolvedValueOnce({
      crews_used: 2,
      assignments: [assignment],
      total_deadhead_minutes: 22,
      total_arrival_buffer_minutes: 90,
    })
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Run schedule' }))
    expect(await screen.findByText(/Schedule solved using 2 crew\(s\)\./)).toHaveTextContent(
      'Total deadhead 22 min; 90 min of slack before the bells.',
    )

    vi.mocked(api.runSchedule).mockResolvedValueOnce({
      crews_used: 1,
      assignments: [assignment],
      total_deadhead_minutes: null,
      total_arrival_buffer_minutes: null,
    })
    await user.click(screen.getByRole('button', { name: 'Run schedule' }))
    await waitFor(() =>
      expect(screen.getByText(/Schedule solved using 1 crew\(s\)\./)).not.toHaveTextContent(
        'Total deadhead',
      ),
    )
  })

  it('generates the day from templates for the selected date and reports what changed', async () => {
    vi.mocked(api.generateFromTemplates).mockResolvedValue({
      service_date: today(),
      runs_created: 2,
      runs_already_existing: 1,
      crews_created: 3,
      crews_already_existing: 0,
      crews_skipped_absent_driver_ids: [driverRecord.id],
      crews_skipped_out_of_service_template_ids: [7],
      crews_skipped_unlicensed_template_ids: [],
    })
    const user = userEvent.setup()
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Generate from templates' }))

    await waitFor(() => expect(api.generateFromTemplates).toHaveBeenCalledWith(today()))
    const status = await screen.findByText(/Generated 2 run\(s\) and 3 crew\(s\)/)
    expect(status).toHaveTextContent('1 already existed and were left unchanged')
    expect(status).toHaveTextContent('skipped crew for absent driver(s): Jordan Driver')
    expect(status).toHaveTextContent(
      'skipped 1 crew template(s) whose bus is out of service or driver is deactivated',
    )
    expect(status).toHaveTextContent('then run the schedule')
    // Generation never solves on its own.
    expect(api.runSchedule).not.toHaveBeenCalled()
  })

  it('flags an assignment whose crew became unavailable after it was made', async () => {
    vi.mocked(api.getAssignments).mockResolvedValue([
      {
        ...assignment,
        locked: true,
        availability_issue: 'driver absent (sick leave, 00:00-23:59)',
      },
    ])
    render(<SchedulePage />)

    expect(await screen.findByText('Needs cover')).toBeInTheDocument()
    expect(screen.getByText(/driver absent \(sick leave, 00:00-23:59\)/)).toBeInTheDocument()
  })

  it('shows each assignment’s lifecycle state to dispatch', async () => {
    vi.mocked(api.getAssignments).mockResolvedValue([{ ...assignment, status: 'acknowledged' }])
    render(<SchedulePage />)
    expect(await screen.findByText('Acknowledged')).toBeInTheDocument()
  })

  it('shows no availability warning for a healthy assignment', async () => {
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())
    expect(screen.queryByText('Needs cover')).not.toBeInTheDocument()
  })

  it('shows an error when generating from templates fails', async () => {
    vi.mocked(api.generateFromTemplates).mockRejectedValue(new ApiError(403, 'Forbidden'))
    const user = userEvent.setup()
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Generate from templates' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden')
  })

  it('renders a reported fleet position with driver/vehicle names and coordinates', async () => {
    const position: VehiclePosition = {
      crew_id: crew.id,
      driver_id: driverRecord.id,
      driver_full_name: driverRecord.full_name,
      vehicle_id: vehicle.id,
      vehicle_label: vehicle.label,
      location_lat: 29.71,
      location_lon: -95.41,
      recorded_at: new Date().toISOString(),
    }
    vi.mocked(api.getFleetPositions).mockResolvedValue([position])
    render(<SchedulePage />)

    await waitFor(() =>
      expect(screen.getByText(/Jordan Driver — Bus 101: 29.71000, -95.41000/)).toBeInTheDocument(),
    )
    // The same bus on the fleet map, with its schools for context.
    const map = await screen.findByRole('region', { name: 'Fleet map' })
    expect(within(map).getByTitle('Bus 101 — Jordan Driver')).toBeInTheDocument()
    expect(within(map).getByTitle(school.name)).toBeInTheDocument()
  })

  it("shows a bus's GPS track on the fleet map when picked", async () => {
    const position: VehiclePosition = {
      crew_id: crew.id,
      driver_id: driverRecord.id,
      driver_full_name: driverRecord.full_name,
      vehicle_id: vehicle.id,
      vehicle_label: vehicle.label,
      location_lat: 29.72,
      location_lon: -95.42,
      recorded_at: new Date().toISOString(),
    }
    vi.mocked(api.getFleetPositions).mockResolvedValue([position])
    vi.mocked(api.getCrewTrack).mockResolvedValue([
      { location_lat: 29.7, location_lon: -95.4, recorded_at: '2026-10-05T12:00:00Z' },
      { location_lat: 29.72, location_lon: -95.42, recorded_at: '2026-10-05T12:01:00Z' },
    ])
    render(<SchedulePage />)
    const picker = await screen.findByLabelText("Show a bus's track")
    const map = await screen.findByRole('region', { name: 'Fleet map' })
    expect(map.querySelector('path.map-track')).toBeNull()

    const user = userEvent.setup()
    await user.selectOptions(picker, String(crew.id))

    await waitFor(() => expect(api.getCrewTrack).toHaveBeenCalledWith(expect.any(String), crew.id))
    await waitFor(() => expect(map.querySelector('path.map-track')).not.toBeNull())

    await user.selectOptions(picker, '')
    await waitFor(() => expect(map.querySelector('path.map-track')).toBeNull())
  })

  it('shows a status message when no vehicle has reported a position yet', async () => {
    render(<SchedulePage />)

    await waitFor(() =>
      expect(
        screen.getByText('No vehicle has reported a position for this date yet.'),
      ).toBeInTheDocument(),
    )
  })

  it('renders a driver report with resolved driver/vehicle names', async () => {
    vi.mocked(api.getDriverReportsForDate).mockResolvedValue([
      {
        id: 1,
        driver_id: driverRecord.id,
        vehicle_id: vehicle.id,
        service_date: '2026-09-01',
        report_type: 'vehicle_defect',
        description: 'Squeaky brakes.',
        created_at: '2026-09-01T12:00:00Z',
      },
    ])
    render(<SchedulePage />)

    await waitFor(() =>
      expect(screen.getByText(/Jordan Driver — Bus 101: Squeaky brakes\./)).toBeInTheDocument(),
    )
  })

  it('shows a status message when there are no driver reports yet', async () => {
    render(<SchedulePage />)

    await waitFor(() =>
      expect(
        screen.getByText('No incident or vehicle defect reports for this date.'),
      ).toBeInTheDocument(),
    )
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
    await user.selectOptions(screen.getByLabelText('Direction'), 'pm')
    await user.type(screen.getByLabelText('Window start (minute of day)'), '480')
    await user.type(screen.getByLabelText('Window end (minute of day)'), '540')
    await user.type(screen.getByLabelText('Duration (minutes)'), '45')
    await user.click(screen.getByRole('checkbox', { name: /lift/ }))
    await user.click(screen.getByRole('button', { name: 'Add run' }))

    await waitFor(() =>
      expect(api.createRun).toHaveBeenCalledWith(
        expect.objectContaining({
          school_id: school.id,
          direction: 'pm',
          window_earliest: 480,
          window_latest: 540,
          duration_minutes: 45,
          required_qualification_codes: ['lift'],
        }),
      ),
    )
    expect(api.getRuns).toHaveBeenCalledTimes(2) // initial load + reload after create
  })

  it('checking observed duration shows the average and lets the dispatcher use it', async () => {
    vi.mocked(api.getObservedRunDuration).mockResolvedValue({
      sample_count: 2,
      average_actual_minutes: 48,
      most_recent_actual_minutes: 56,
      most_recent_service_date: '2026-09-02',
    })
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('School'), String(school.id))
    await user.click(screen.getByRole('button', { name: 'Check observed duration' }))

    await waitFor(() => expect(api.getObservedRunDuration).toHaveBeenCalledWith(school.id, 'am'))
    expect(screen.getByText(/2 completed run\(s\) — average 48 min/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Use average' }))
    expect(screen.getByLabelText('Duration (minutes)')).toHaveValue(48)
  })

  it('shows a message and no Use-average button when there are no observed runs yet', async () => {
    vi.mocked(api.getObservedRunDuration).mockResolvedValue({
      sample_count: 0,
      average_actual_minutes: null,
      most_recent_actual_minutes: null,
      most_recent_service_date: null,
    })
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('School'), String(school.id))
    await user.click(screen.getByRole('button', { name: 'Check observed duration' }))

    await waitFor(() =>
      expect(
        screen.getByText('No completed runs yet for this school/direction.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByRole('button', { name: 'Use average' })).not.toBeInTheDocument()
  })

  it('checking expected riders shows the computed count and lets the dispatcher apply it', async () => {
    vi.mocked(api.getExpectedRiders).mockResolvedValue({
      expected_passenger_count: 5,
      ambiguous: false,
      riding_student_names: ['Alex Rider', 'Sam Rider'],
    })
    vi.mocked(api.updateRun).mockResolvedValue({ ...run, passenger_count: 5 })
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Check expected riders' }))

    await waitFor(() => expect(screen.getByText(/Expected riders: 5/)).toBeInTheDocument())
    expect(screen.getByText(/Alex Rider, Sam Rider/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Apply to passenger_count' }))

    await waitFor(() => expect(api.updateRun).toHaveBeenCalledWith(run.id, { passenger_count: 5 }))
  })

  it('disables Apply and shows a warning when expected riders is ambiguous', async () => {
    vi.mocked(api.getExpectedRiders).mockResolvedValue({
      expected_passenger_count: 5,
      ambiguous: true,
      riding_student_names: [],
    })
    render(<SchedulePage />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Crew' })).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Check expected riders' }))

    await waitFor(() => expect(screen.getByText(/Ambiguous/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Apply to passenger_count' })).toBeDisabled()
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
      crew_id: 20,
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
    const panel = (
      await screen.findByRole('heading', { level: 3, name: /^Substitutes for/ })
    ).closest('div') as HTMLElement
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
      crew_id: 20,
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

  it('assigning a substitute with no existing crew that day repoints the affected crew instead of creating a new one', async () => {
    const affected: AffectedAssignmentSubstitutes = {
      assignment_id: 100,
      run_id: 10,
      school_name: 'Riverside Elementary',
      start_minute: 360,
      end_minute: 410,
      crew_id: 20,
      vehicle_id: 3,
      vehicle_label: 'Bus 101',
      candidates: [{ driver_id: 6, full_name: 'Casey NoCrew', score: 0, reasons: ['available'] }],
    }
    vi.mocked(api.getSubstituteCandidates).mockResolvedValue([affected])
    vi.mocked(api.updateCrewDriver).mockResolvedValue({ ...crew, driver_id: 6 })
    render(<SchedulePage />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Find substitutes' })).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Find substitutes' }))
    await screen.findByRole('button', { name: 'Assign as substitute' })
    await user.click(screen.getByRole('button', { name: 'Assign as substitute' }))

    await waitFor(() => expect(api.updateCrewDriver).toHaveBeenCalledWith(20, 6))
    expect(api.createCrew).not.toHaveBeenCalled()
    expect(api.updateAssignment).not.toHaveBeenCalled()
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
