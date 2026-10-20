import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Driver, FieldTrip, Qualification, Vehicle } from '../api/types'
import { FieldTripsPage } from './FieldTripsPage'
import { axeViolations } from '../test/axe'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getFieldTrips: vi.fn(),
    getDrivers: vi.fn(),
    getVehicles: vi.fn(),
    getQualifications: vi.fn(),
    createFieldTrip: vi.fn(),
    updateFieldTrip: vi.fn(),
    getFieldTripConflicts: vi.fn(),
    getFieldTripObservedDuration: vi.fn(),
    getDestinationProfiles: vi.fn(),
    createDestinationProfile: vi.fn(),
  }
})

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

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
  vehicle_type: null,
  wheelchair_positions: null,
  turning_radius_m: null,
  required_license_class: 'cdl_b',
  is_active: true,
  qualifications: [],
}
const trip: FieldTrip = {
  id: 1,
  requesting_party: 'Science Department',
  origin: 'Riverside Elementary',
  destination: 'State Science Museum',
  destination_profile_id: null,
  destination_profile: null,
  departure_at: `${today()}T13:00:00Z`,
  expected_return_at: `${today()}T16:00:00Z`,
  actual_return_at: null,
  passenger_count: 30,
  assigned_driver_id: null,
  assigned_vehicle_id: null,
  bus_assistant_name: null,
  trip_contact: 'Ms. Rivera, 555-0100',
  special_instructions: null,
  status: 'requested',
  required_qualifications: [],
}

function mockLoad() {
  vi.mocked(api.getFieldTrips).mockResolvedValue([trip])
  vi.mocked(api.getDrivers).mockResolvedValue([driverRecord])
  vi.mocked(api.getVehicles).mockResolvedValue([vehicle])
  vi.mocked(api.getQualifications).mockResolvedValue([] as Qualification[])
  vi.mocked(api.getDestinationProfiles).mockResolvedValue([])
}

// Every state these tests reach is checked against WCAG 2.1 A/AA.
afterEach(async () => {
  expect(await axeViolations()).toEqual([])
})

describe('FieldTripsPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockLoad()
  })

  it('renders a field trip card with requesting party, route, and status', async () => {
    render(<FieldTripsPage />)

    await waitFor(() => expect(screen.getByText(/Science Department/)).toBeInTheDocument())
    expect(screen.getByText(/Riverside Elementary/)).toBeInTheDocument()
    expect(screen.getByText(/State Science Museum/)).toBeInTheDocument()
    expect(screen.getByText(/30 passengers/)).toBeInTheDocument()
  })

  it('shows a friendly message when there are no trips for the date', async () => {
    vi.mocked(api.getFieldTrips).mockResolvedValue([])
    render(<FieldTripsPage />)

    await waitFor(() =>
      expect(screen.getByText('No field trips scheduled for this date.')).toBeInTheDocument(),
    )
  })

  it('creating a field trip sends the form fields and reloads', async () => {
    vi.mocked(api.createFieldTrip).mockResolvedValue({ ...trip, id: 99 })
    render(<FieldTripsPage />)
    await waitFor(() => expect(screen.getByText(/Science Department/)).toBeInTheDocument())

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Requesting school/department'), 'Athletics')
    await user.type(screen.getByLabelText('Origin'), 'High School')
    await user.type(screen.getByLabelText('Destination'), 'Away Game')
    await user.type(screen.getByLabelText('Departure'), '2026-09-01T13:00')
    await user.type(screen.getByLabelText('Expected return'), '2026-09-01T18:00')
    await user.type(screen.getByLabelText('Trip contact'), 'Coach Lee')
    await user.click(screen.getByRole('button', { name: 'Add field trip' }))

    await waitFor(() =>
      expect(api.createFieldTrip).toHaveBeenCalledWith(
        expect.objectContaining({
          requesting_party: 'Athletics',
          origin: 'High School',
          destination: 'Away Game',
          trip_contact: 'Coach Lee',
        }),
      ),
    )
  })

  it('checking observed duration shows the average and fills in a suggested return time', async () => {
    vi.mocked(api.getFieldTripObservedDuration).mockResolvedValue({
      sample_count: 2,
      average_actual_minutes: 180,
      most_recent_actual_minutes: 210,
      most_recent_departure_date: '2026-09-08',
    })
    render(<FieldTripsPage />)
    await waitFor(() => expect(screen.getByText(/Science Department/)).toBeInTheDocument())

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Destination'), 'Away Game')
    await user.type(screen.getByLabelText('Departure'), '2026-09-01T13:00')
    await user.click(screen.getByRole('button', { name: 'Check observed duration' }))

    await waitFor(() =>
      expect(api.getFieldTripObservedDuration).toHaveBeenCalledWith({ destination: 'Away Game' }),
    )
    expect(screen.getByText(/2 completed trip\(s\) — average 180 min/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Use average to suggest return time' }))
    expect(screen.getByLabelText('Expected return')).toHaveValue('2026-09-01T16:00')
  })

  it('creating a destination profile calls the API with the entered fields and reloads', async () => {
    vi.mocked(api.createDestinationProfile).mockResolvedValue({
      id: 1,
      name: 'State Science Museum',
      location_lat: null,
      location_lon: null,
      approved_entrance: 'North doors',
      parking_notes: null,
      turn_restrictions: null,
      driver_notes: null,
      created_at: '2026-09-01T12:00:00Z',
    })
    render(<FieldTripsPage />)
    await waitFor(() => expect(screen.getByText(/Science Department/)).toBeInTheDocument())

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Name'), 'State Science Museum')
    await user.type(screen.getByLabelText('Approved entrance'), 'North doors')
    await user.click(screen.getByRole('button', { name: 'Add destination profile' }))

    await waitFor(() =>
      expect(api.createDestinationProfile).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'State Science Museum', approved_entrance: 'North doors' }),
      ),
    )
    expect(api.getDestinationProfiles).toHaveBeenCalledTimes(2) // initial load + reload after create
  })

  it('checking conflicts shows the returned list and disables Assign', async () => {
    vi.mocked(api.getFieldTripConflicts).mockResolvedValue({
      conflicts: ['Regular route at Riverside Elementary (360-410) overlaps this trip'],
      routes_needing_cover: [],
      turnaround_minutes: 15,
    })
    render(<FieldTripsPage />)
    await waitFor(() => expect(screen.getByText(/Science Department/)).toBeInTheDocument())

    const card = screen.getByText(/Science Department/).closest('li') as HTMLElement
    const user = userEvent.setup()
    await user.selectOptions(within(card).getByLabelText('Candidate driver'), 'Jordan Driver')
    await user.click(within(card).getByRole('button', { name: 'Check conflicts' }))

    await waitFor(() =>
      expect(
        screen.getByText('Regular route at Riverside Elementary (360-410) overlaps this trip'),
      ).toBeInTheDocument(),
    )
    expect(within(card).getByRole('button', { name: 'Assign' })).toBeDisabled()
  })

  it('assigning with no conflicts calls updateFieldTrip with the candidate driver/vehicle', async () => {
    vi.mocked(api.updateFieldTrip).mockResolvedValue({
      ...trip,
      status: 'assigned',
      assigned_driver_id: driverRecord.id,
      assigned_vehicle_id: vehicle.id,
    })
    render(<FieldTripsPage />)
    await waitFor(() => expect(screen.getByText(/Science Department/)).toBeInTheDocument())

    const card = screen.getByText(/Science Department/).closest('li') as HTMLElement
    const user = userEvent.setup()
    await user.selectOptions(within(card).getByLabelText('Candidate driver'), 'Jordan Driver')
    await user.selectOptions(within(card).getByLabelText('Candidate vehicle'), 'Bus 101')
    await user.click(within(card).getByRole('button', { name: 'Assign' }))

    await waitFor(() =>
      expect(api.updateFieldTrip).toHaveBeenCalledWith(1, {
        status: 'assigned',
        assigned_driver_id: driverRecord.id,
        assigned_vehicle_id: vehicle.id,
      }),
    )
  })

  it('changing the status select calls updateFieldTrip with the new status', async () => {
    vi.mocked(api.updateFieldTrip).mockResolvedValue({ ...trip, status: 'approved' })
    render(<FieldTripsPage />)
    await waitFor(() => expect(screen.getByText(/Science Department/)).toBeInTheDocument())

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Status for field trip 1'), 'approved')

    await waitFor(() => expect(api.updateFieldTrip).toHaveBeenCalledWith(1, { status: 'approved' }))
  })

  it('shows the server error message when creating a field trip fails', async () => {
    vi.mocked(api.createFieldTrip).mockRejectedValue(
      new ApiError(400, 'departure_at must be before expected_return_at'),
    )
    render(<FieldTripsPage />)
    await waitFor(() => expect(screen.getByText(/Science Department/)).toBeInTheDocument())

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Requesting school/department'), 'Athletics')
    await user.type(screen.getByLabelText('Origin'), 'High School')
    await user.type(screen.getByLabelText('Destination'), 'Away Game')
    await user.type(screen.getByLabelText('Departure'), '2026-09-01T18:00')
    await user.type(screen.getByLabelText('Expected return'), '2026-09-01T13:00')
    await user.type(screen.getByLabelText('Trip contact'), 'Coach Lee')
    await user.click(screen.getByRole('button', { name: 'Add field trip' }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'departure_at must be before expected_return_at',
      ),
    )
  })

  it('offers no return-time control for a trip that has no driver or bus yet', async () => {
    render(<FieldTripsPage />)
    await waitFor(() => expect(screen.getByText(/Science Department/)).toBeInTheDocument())
    expect(screen.queryByLabelText('Revised return time')).not.toBeInTheDocument()
  })

  it('delaying an assigned trip saves the new return time and lists routes that now need cover', async () => {
    vi.mocked(api.getFieldTrips).mockResolvedValue([
      { ...trip, status: 'assigned', assigned_driver_id: driverRecord.id },
    ])
    const route =
      'Regular route at Riverside Elementary on 2026-10-08 (14:15-14:45) overlaps this trip'
    vi.mocked(api.updateFieldTrip).mockResolvedValue({ ...trip, status: 'assigned' })
    vi.mocked(api.getFieldTripConflicts).mockResolvedValue({
      conflicts: [route],
      routes_needing_cover: [route],
      turnaround_minutes: 15,
    })
    render(<FieldTripsPage />)
    const input = await screen.findByLabelText('Revised return time')
    const user = userEvent.setup()

    // Unchanged, there's nothing to save.
    expect(screen.getByRole('button', { name: 'Update return time' })).toBeDisabled()
    fireEvent.change(input, { target: { value: `${today()}T17:30` } })
    await user.click(screen.getByRole('button', { name: 'Update return time' }))

    await waitFor(() =>
      expect(api.updateFieldTrip).toHaveBeenCalledWith(trip.id, {
        expected_return_at: `${today()}T17:30`,
      }),
    )
    expect(api.getFieldTripConflicts).toHaveBeenCalledWith(trip.id)
    expect(await screen.findByText(/These routes now need cover/)).toBeInTheDocument()
    expect(screen.getByText(route)).toBeInTheDocument()
  })

  it('says so when a delay affects no regular routes', async () => {
    vi.mocked(api.getFieldTrips).mockResolvedValue([
      { ...trip, status: 'assigned', assigned_vehicle_id: vehicle.id },
    ])
    vi.mocked(api.updateFieldTrip).mockResolvedValue({ ...trip, status: 'assigned' })
    vi.mocked(api.getFieldTripConflicts).mockResolvedValue({
      conflicts: [],
      routes_needing_cover: [],
      turnaround_minutes: 15,
    })
    render(<FieldTripsPage />)
    const input = await screen.findByLabelText('Revised return time')
    const user = userEvent.setup()
    fireEvent.change(input, { target: { value: `${today()}T16:45` } })
    await user.click(screen.getByRole('button', { name: 'Update return time' }))

    expect(await screen.findByText('No regular routes are affected.')).toBeInTheDocument()
  })
})
