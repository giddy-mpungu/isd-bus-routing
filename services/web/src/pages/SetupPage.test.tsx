import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { CurrentUser, Driver, Qualification, School, Vehicle } from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { SetupPage } from './SetupPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getCurrentUser: vi.fn(),
    getSchools: vi.fn(),
    getQualifications: vi.fn(),
    getDrivers: vi.fn(),
    getVehicles: vi.fn(),
    getStops: vi.fn(),
    getStudents: vi.fn(),
    createSchool: vi.fn(),
    createQualification: vi.fn(),
    createDriver: vi.fn(),
    createVehicle: vi.fn(),
    createStop: vi.fn(),
    createStudent: vi.fn(),
  }
})

const adminUser: CurrentUser = {
  id: 1,
  email: 'admin@example.org',
  full_name: 'Admin',
  role: 'transportation_admin',
  is_active: true,
  driver_id: null,
  school_id: null,
  student_id: null,
}
const dispatcherUser: CurrentUser = { ...adminUser, role: 'dispatcher' }

const school: School = {
  id: 1,
  name: 'Riverside Elementary',
  location_lat: 29.7,
  location_lon: -95.4,
}
const licenseQual: Qualification = { id: 1, code: 'CDL_B', kind: 'license', description: null }
const vehicleQual: Qualification = {
  id: 2,
  code: 'lift',
  kind: 'vehicle_capability',
  description: 'Wheelchair lift',
}
const driver: Driver = {
  id: 1,
  full_name: 'Jordan Driver',
  max_continuous_minutes: null,
  qualifications: [],
}
const vehicle: Vehicle = {
  id: 1,
  label: 'Bus 101',
  nominal_capacity: 48,
  effective_capacity: 44,
  qualifications: [],
}

function mockLoad() {
  vi.mocked(api.getSchools).mockResolvedValue([school])
  vi.mocked(api.getQualifications).mockResolvedValue([licenseQual, vehicleQual])
  vi.mocked(api.getDrivers).mockResolvedValue([driver])
  vi.mocked(api.getVehicles).mockResolvedValue([vehicle])
  vi.mocked(api.getStops).mockResolvedValue([])
  vi.mocked(api.getStudents).mockResolvedValue([])
}

function renderAsRole(user: CurrentUser) {
  vi.mocked(api.getCurrentUser).mockResolvedValue(user)
  return render(
    <AuthProvider>
      <SetupPage />
    </AuthProvider>,
  )
}

describe('SetupPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockLoad()
  })

  it('shows create forms for transportation_admin', async () => {
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Add school' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add qualification' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add driver' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add vehicle' })).toBeInTheDocument()
  })

  it('hides create forms for dispatcher, but still shows the lists', async () => {
    renderAsRole(dispatcherUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    expect(screen.queryByRole('button', { name: 'Add school' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add driver' })).not.toBeInTheDocument()
  })

  it('only offers license qualifications on the driver form and vehicle_capability ones on the vehicle form', async () => {
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    // CDL_B (license) is offered as a driver checkbox but not a vehicle one.
    expect(screen.getAllByText('CDL_B', { exact: false })).toHaveLength(2) // list item + checkbox label
    const vehicleFieldset = screen.getByRole('group', { name: 'Vehicle capability qualifications' })
    expect(vehicleFieldset).not.toHaveTextContent('CDL_B')
    const driverFieldset = screen.getByRole('group', { name: 'License qualifications' })
    expect(driverFieldset).not.toHaveTextContent('lift')
  })

  it('creating a school calls the API and reloads the list', async () => {
    vi.mocked(api.createSchool).mockResolvedValue({
      id: 2,
      name: 'Northside Middle',
      location_lat: 29.8,
      location_lon: -95.5,
    })
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Name'), 'Northside Middle')
    await user.type(screen.getByLabelText('Latitude'), '29.8')
    await user.type(screen.getByLabelText('Longitude'), '-95.5')
    await user.click(screen.getByRole('button', { name: 'Add school' }))

    await waitFor(() =>
      expect(api.createSchool).toHaveBeenCalledWith({
        name: 'Northside Middle',
        location_lat: 29.8,
        location_lon: -95.5,
      }),
    )
    expect(api.getSchools).toHaveBeenCalledTimes(2) // initial load + reload after create
  })

  it('creating a driver sends the selected qualification codes', async () => {
    vi.mocked(api.createDriver).mockResolvedValue({ ...driver, id: 2 })
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Full name'), 'Sam Substitute')
    await user.click(screen.getByRole('checkbox', { name: /CDL_B/ }))
    await user.click(screen.getByRole('button', { name: 'Add driver' }))

    await waitFor(() =>
      expect(api.createDriver).toHaveBeenCalledWith({
        full_name: 'Sam Substitute',
        max_continuous_minutes: undefined,
        qualification_codes: ['CDL_B'],
      }),
    )
  })

  it('shows the server error message on a failed creation', async () => {
    vi.mocked(api.createSchool).mockRejectedValue(new ApiError(403, 'Not authorized'))
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Name'), 'X')
    await user.type(screen.getByLabelText('Latitude'), '1')
    await user.type(screen.getByLabelText('Longitude'), '1')
    await user.click(screen.getByRole('button', { name: 'Add school' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Not authorized'))
  })
})
