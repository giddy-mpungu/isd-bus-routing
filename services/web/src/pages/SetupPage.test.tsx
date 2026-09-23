import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
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
    getOptimizationSettings: vi.fn(),
    getSchools: vi.fn(),
    getQualifications: vi.fn(),
    getDrivers: vi.fn(),
    getVehicles: vi.fn(),
    getStops: vi.fn(),
    getStudents: vi.fn(),
    getGeographicKnowledgeOverrides: vi.fn(),
    getAnnouncements: vi.fn(),
    createSchool: vi.fn(),
    createQualification: vi.fn(),
    createDriver: vi.fn(),
    createVehicle: vi.fn(),
    createStop: vi.fn(),
    createStudent: vi.fn(),
    createGeographicKnowledgeOverride: vi.fn(),
    createAnnouncement: vi.fn(),
    getAuditLog: vi.fn(),
    getAuditLogEntityTypes: vi.fn(),
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
const licenseQual: Qualification = {
  id: 1,
  code: 'CDL_B',
  kind: 'license',
  description: null,
  is_active: true,
}
const vehicleQual: Qualification = {
  id: 2,
  code: 'lift',
  kind: 'vehicle_capability',
  description: 'Wheelchair lift',
  is_active: true,
}
const driver: Driver = {
  id: 1,
  full_name: 'Jordan Driver',
  max_continuous_minutes: null,
  is_active: true,
  qualifications: [],
}
const vehicle: Vehicle = {
  id: 1,
  label: 'Bus 101',
  nominal_capacity: 48,
  effective_capacity: 44,
  length_m: null,
  width_m: null,
  height_m: null,
  weight_kg: null,
  is_active: true,
  qualifications: [],
}

function mockLoad() {
  vi.mocked(api.getSchools).mockResolvedValue([school])
  vi.mocked(api.getQualifications).mockResolvedValue([licenseQual, vehicleQual])
  vi.mocked(api.getDrivers).mockResolvedValue([driver])
  vi.mocked(api.getVehicles).mockResolvedValue([vehicle])
  vi.mocked(api.getStops).mockResolvedValue([])
  vi.mocked(api.getStudents).mockResolvedValue([])
  vi.mocked(api.getGeographicKnowledgeOverrides).mockResolvedValue([])
  vi.mocked(api.getAnnouncements).mockResolvedValue([])
  vi.mocked(api.getOptimizationSettings).mockResolvedValue({
    crews_used_weight: 1,
    deadhead_minutes_weight: 0,
    arrival_buffer_weight: 0,
    is_default: true,
  })
}

function renderAsRole(user: CurrentUser, initialEntry = '/setup') {
  vi.mocked(api.getCurrentUser).mockResolvedValue(user)
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AuthProvider>
        <SetupPage />
      </AuthProvider>
    </MemoryRouter>,
  )
}

// Every Setup section lives in a tab; only the active tab's panel is
// visible (and so reachable by role queries), like it is for a real user.
async function openTab(name: RegExp) {
  await userEvent.setup().click(screen.getByRole('tab', { name }))
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
    expect(screen.getByRole('button', { name: 'Add student' })).toBeInTheDocument()
    await openTab(/Fleet & drivers/)
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
    await openTab(/Fleet & drivers/)
    expect(screen.getByText('Jordan Driver', { exact: false })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add driver' })).not.toBeInTheDocument()
  })

  it('shows the district geographic knowledge form for dispatcher too, unlike the admin-only sections', async () => {
    renderAsRole(dispatcherUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/District knowledge/)
    expect(screen.getByRole('button', { name: 'Add override' })).toBeInTheDocument()
  })

  it('creating a district geographic knowledge override calls the API and reloads the list', async () => {
    vi.mocked(api.createGeographicKnowledgeOverride).mockResolvedValue({
      id: 1,
      location_lat: 29.7,
      location_lon: -95.4,
      category: 'frequent_flooding',
      note: 'Elm St floods after heavy rain.',
      window_start_minute: null,
      window_end_minute: null,
      restricted_dimension: null,
      max_allowed_value: null,
      school_id: null,
      created_at: '2026-09-08T12:00:00Z',
    })
    renderAsRole(dispatcherUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/District knowledge/)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Override latitude'), '29.7')
    await user.type(screen.getByLabelText('Override longitude'), '-95.4')
    await user.type(screen.getByLabelText('Note'), 'Elm St floods after heavy rain.')
    await user.click(screen.getByRole('button', { name: 'Add override' }))

    await waitFor(() =>
      expect(api.createGeographicKnowledgeOverride).toHaveBeenCalledWith({
        location_lat: 29.7,
        location_lon: -95.4,
        category: 'frequent_flooding',
        note: 'Elm St floods after heavy rain.',
        window_start_minute: null,
        window_end_minute: null,
        restricted_dimension: null,
        max_allowed_value: null,
        school_id: null,
      }),
    )
    expect(api.getGeographicKnowledgeOverrides).toHaveBeenCalledTimes(2) // initial load + reload after create
  })

  it('creating a congestion_window override sends its time range and no size-restriction fields', async () => {
    vi.mocked(api.createGeographicKnowledgeOverride).mockResolvedValue({
      id: 2,
      location_lat: 29.7,
      location_lon: -95.4,
      category: 'congestion_window',
      note: 'Backs up during morning drop-off.',
      window_start_minute: 420,
      window_end_minute: 480,
      restricted_dimension: null,
      max_allowed_value: null,
      school_id: null,
      created_at: '2026-09-17T12:00:00Z',
    })
    renderAsRole(dispatcherUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/District knowledge/)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Override latitude'), '29.7')
    await user.type(screen.getByLabelText('Override longitude'), '-95.4')
    await user.selectOptions(screen.getByLabelText('Category'), 'congestion_window')
    await user.type(screen.getByLabelText('Congestion window start (minute of day)'), '420')
    await user.type(screen.getByLabelText('Congestion window end (minute of day)'), '480')
    await user.type(screen.getByLabelText('Note'), 'Backs up during morning drop-off.')
    await user.click(screen.getByRole('button', { name: 'Add override' }))

    await waitFor(() =>
      expect(api.createGeographicKnowledgeOverride).toHaveBeenCalledWith({
        location_lat: 29.7,
        location_lon: -95.4,
        category: 'congestion_window',
        note: 'Backs up during morning drop-off.',
        window_start_minute: 420,
        window_end_minute: 480,
        restricted_dimension: null,
        max_allowed_value: null,
        school_id: null,
      }),
    )
  })

  it('creating a vehicle_size_restricted override sends its dimension/threshold and no window fields', async () => {
    vi.mocked(api.createGeographicKnowledgeOverride).mockResolvedValue({
      id: 3,
      location_lat: 29.7,
      location_lon: -95.4,
      category: 'vehicle_size_restricted',
      note: 'Covered bridge has a 3.0m height limit.',
      window_start_minute: null,
      window_end_minute: null,
      restricted_dimension: 'height_m',
      max_allowed_value: 3.0,
      school_id: null,
      created_at: '2026-09-17T12:00:00Z',
    })
    renderAsRole(dispatcherUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/District knowledge/)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Override latitude'), '29.7')
    await user.type(screen.getByLabelText('Override longitude'), '-95.4')
    await user.selectOptions(screen.getByLabelText('Category'), 'vehicle_size_restricted')
    await user.selectOptions(screen.getByLabelText('Restricted dimension'), 'height_m')
    await user.type(screen.getByLabelText('Max allowed value'), '3')
    await user.type(screen.getByLabelText('Note'), 'Covered bridge has a 3.0m height limit.')
    await user.click(screen.getByRole('button', { name: 'Add override' }))

    await waitFor(() =>
      expect(api.createGeographicKnowledgeOverride).toHaveBeenCalledWith({
        location_lat: 29.7,
        location_lon: -95.4,
        category: 'vehicle_size_restricted',
        note: 'Covered bridge has a 3.0m height limit.',
        window_start_minute: null,
        window_end_minute: null,
        restricted_dimension: 'height_m',
        max_allowed_value: 3,
        school_id: null,
      }),
    )
  })

  it('creating a preferred_entrance override sends its school_id and no window/threshold fields', async () => {
    vi.mocked(api.createGeographicKnowledgeOverride).mockResolvedValue({
      id: 4,
      location_lat: 29.71,
      location_lon: -95.41,
      category: 'preferred_entrance',
      note: 'Use the north gate, not the main office.',
      window_start_minute: null,
      window_end_minute: null,
      restricted_dimension: null,
      max_allowed_value: null,
      school_id: 1,
      created_at: '2026-09-17T12:00:00Z',
    })
    renderAsRole(dispatcherUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/District knowledge/)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Override latitude'), '29.71')
    await user.type(screen.getByLabelText('Override longitude'), '-95.41')
    await user.selectOptions(screen.getByLabelText('Category'), 'preferred_entrance')
    await user.selectOptions(screen.getByLabelText('School'), 'Riverside Elementary')
    await user.type(screen.getByLabelText('Note'), 'Use the north gate, not the main office.')
    await user.click(screen.getByRole('button', { name: 'Add override' }))

    await waitFor(() =>
      expect(api.createGeographicKnowledgeOverride).toHaveBeenCalledWith({
        location_lat: 29.71,
        location_lon: -95.41,
        category: 'preferred_entrance',
        note: 'Use the north gate, not the main office.',
        window_start_minute: null,
        window_end_minute: null,
        restricted_dimension: null,
        max_allowed_value: null,
        school_id: 1,
      }),
    )
  })

  it('creating an announcement calls the API with message/category/audience and reloads', async () => {
    vi.mocked(api.createAnnouncement).mockResolvedValue({
      id: 1,
      message: 'Buses running 15 minutes late today.',
      category: 'delay',
      audience: 'family',
      school_id: null,
      created_at: '2026-09-14T12:00:00Z',
    })
    renderAsRole(dispatcherUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/Announcements/)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Message'), 'Buses running 15 minutes late today.')
    await user.selectOptions(screen.getByLabelText('Announcement category'), 'delay')
    await user.selectOptions(screen.getByLabelText('Audience'), 'family')
    await user.click(screen.getByRole('button', { name: 'Post announcement' }))

    await waitFor(() =>
      expect(api.createAnnouncement).toHaveBeenCalledWith({
        message: 'Buses running 15 minutes late today.',
        category: 'delay',
        audience: 'family',
        school_id: null,
      }),
    )
    expect(api.getAnnouncements).toHaveBeenCalledTimes(2) // initial load + reload after create
  })

  it('creating a school-scoped announcement sends the selected school_id', async () => {
    vi.mocked(api.createAnnouncement).mockResolvedValue({
      id: 2,
      message: 'Riverside dismissal moved up 15 minutes.',
      category: 'general',
      audience: 'family',
      school_id: 1,
      created_at: '2026-09-14T12:00:00Z',
    })
    renderAsRole(dispatcherUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/Announcements/)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Message'), 'Riverside dismissal moved up 15 minutes.')
    await user.selectOptions(screen.getByLabelText('Audience'), 'family')
    // Not just /School/: the "Schools & students" tab also labels its panel.
    await user.selectOptions(screen.getByLabelText(/^School \(optional/), 'Riverside Elementary')
    await user.click(screen.getByRole('button', { name: 'Post announcement' }))

    await waitFor(() =>
      expect(api.createAnnouncement).toHaveBeenCalledWith(
        expect.objectContaining({ school_id: 1 }),
      ),
    )
  })

  it('only offers license qualifications on the driver form and vehicle_capability ones on the vehicle form', async () => {
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/Fleet & drivers/)
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
    await openTab(/Fleet & drivers/)

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

  it('creating a vehicle sends the dimension fields', async () => {
    vi.mocked(api.createVehicle).mockResolvedValue({ ...vehicle, id: 2 })
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/Fleet & drivers/)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Label'), 'Bus 202')
    await user.type(screen.getByLabelText('Length in meters (optional)'), '10.5')
    await user.type(screen.getByLabelText('Width in meters (optional)'), '2.5')
    await user.type(screen.getByLabelText('Height in meters (optional)'), '3.2')
    await user.type(screen.getByLabelText('Weight in kg (optional)'), '12000')
    await user.click(screen.getByRole('button', { name: 'Add vehicle' }))

    await waitFor(() =>
      expect(api.createVehicle).toHaveBeenCalledWith({
        label: 'Bus 202',
        nominal_capacity: undefined,
        effective_capacity: undefined,
        length_m: 10.5,
        width_m: 2.5,
        height_m: 3.2,
        weight_kg: 12000,
        qualification_codes: [],
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

  it('shows the audit log section for transportation_admin', async () => {
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/Audit log/)
    expect(screen.getByRole('heading', { name: 'Audit log' })).toBeInTheDocument()
  })

  it('hides the audit log section for dispatcher', async () => {
    renderAsRole(dispatcherUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    expect(screen.queryByRole('tab', { name: /Audit log/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /SIS import/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Audit log' })).not.toBeInTheDocument()
  })

  it('loading the audit log fetches entity types and entries, and renders them', async () => {
    vi.mocked(api.getAuditLogEntityTypes).mockResolvedValue(['announcement', 'school'])
    vi.mocked(api.getAuditLog).mockResolvedValue([
      {
        id: 1,
        entity_type: 'announcement',
        entity_id: 5,
        action: 'created',
        actor_user_id: 1,
        actor_full_name: 'Admin',
        before_state: null,
        after_state: { message: 'Buses running late.' },
        created_at: '2026-09-18T12:00:00Z',
      },
    ])
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/Audit log/)

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Load audit log' }))

    await waitFor(() =>
      expect(api.getAuditLog).toHaveBeenCalledWith({
        entity_type: undefined,
        entity_id: undefined,
        limit: 20,
        offset: 0,
      }),
    )
    expect(screen.getByText(/created announcement #5/)).toBeInTheDocument()
    expect(screen.getByText('Admin', { exact: false })).toBeInTheDocument()
  })

  it('filtering the audit log by entity type sends it to the API', async () => {
    vi.mocked(api.getAuditLogEntityTypes).mockResolvedValue(['announcement', 'school'])
    vi.mocked(api.getAuditLog).mockResolvedValue([])
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/Audit log/)

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Load audit log' }))
    await waitFor(() => expect(api.getAuditLog).toHaveBeenCalledTimes(1))

    await user.selectOptions(screen.getByLabelText('Entity type'), 'announcement')
    await user.click(screen.getByRole('button', { name: 'Refresh' }))

    await waitFor(() =>
      expect(api.getAuditLog).toHaveBeenCalledWith({
        entity_type: 'announcement',
        entity_id: undefined,
        limit: 20,
        offset: 0,
      }),
    )
  })

  it('shows a friendly message when the audit log has no matching entries', async () => {
    vi.mocked(api.getAuditLogEntityTypes).mockResolvedValue([])
    vi.mocked(api.getAuditLog).mockResolvedValue([])
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/Audit log/)

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Load audit log' }))

    await waitFor(() =>
      expect(screen.getByText('No matching audit log entries.')).toBeInTheDocument(),
    )
  })

  it('shows an error message when loading the audit log fails', async () => {
    vi.mocked(api.getAuditLogEntityTypes).mockResolvedValue([])
    vi.mocked(api.getAuditLog).mockRejectedValue(new ApiError(403, 'Not authorized'))
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    await openTab(/Audit log/)

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Load audit log' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Not authorized'))
  })

  it('starts on the Schools & students tab and shows only that panel', async () => {
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    expect(screen.getByRole('tab', { name: /Schools & students/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('heading', { name: 'Schools' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Drivers' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('tabpanel')).toHaveLength(1)
  })

  it('opens the tab named in the ?tab= query parameter', async () => {
    renderAsRole(adminUser, '/setup?tab=announcements')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Post announcement' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('tab', { name: /Announcements/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('falls back to the first tab for an admin-only tab a dispatcher cannot see', async () => {
    renderAsRole(dispatcherUser, '/setup?tab=audit-log')
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    expect(screen.getByRole('tab', { name: /Schools & students/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.queryByRole('heading', { name: 'Audit log' })).not.toBeInTheDocument()
  })

  it('moves between tabs with the arrow, Home and End keys', async () => {
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    const user = userEvent.setup()
    const first = screen.getByRole('tab', { name: /Schools & students/ })
    first.focus()

    await user.keyboard('{ArrowRight}')
    const fleet = screen.getByRole('tab', { name: /Fleet & drivers/ })
    expect(fleet).toHaveAttribute('aria-selected', 'true')
    expect(fleet).toHaveFocus()

    await user.keyboard('{ArrowLeft}{ArrowLeft}') // wraps around to the last tab
    expect(screen.getByRole('tab', { name: /Audit log/ })).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{Home}')
    expect(first).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{End}')
    expect(screen.getByRole('tab', { name: /Audit log/ })).toHaveFocus()
  })

  it('keeps a half-filled form when switching tabs and back', async () => {
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getAllByText('Riverside Elementary', { exact: false })[0]).toBeInTheDocument(),
    )
    const user = userEvent.setup()
    await openTab(/Fleet & drivers/)
    await user.type(screen.getByLabelText('Label'), 'Bus 303')
    await openTab(/Announcements/)
    await openTab(/Fleet & drivers/)
    expect(screen.getByLabelText('Label')).toHaveValue('Bus 303')
  })

  it('shows record totals, and a total jumps to the tab that manages it', async () => {
    renderAsRole(adminUser)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '1 Active drivers' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: '1 Schools' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '0 Students' })).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole('button', { name: '1 Active vehicles' }))
    expect(screen.getByRole('tab', { name: /Fleet & drivers/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })
})
