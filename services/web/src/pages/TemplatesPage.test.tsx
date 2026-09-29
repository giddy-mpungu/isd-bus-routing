import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  CrewTemplate,
  Driver,
  Qualification,
  RouteTemplate,
  School,
  Vehicle,
} from '../api/types'
import { TemplatesPage } from './TemplatesPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getRouteTemplates: vi.fn(),
    getCrewTemplates: vi.fn(),
    getSchools: vi.fn(),
    getDrivers: vi.fn(),
    getVehicles: vi.fn(),
    getQualifications: vi.fn(),
    getStops: vi.fn(),
    setRouteStops: vi.fn(),
    createRouteTemplate: vi.fn(),
    createCrewTemplate: vi.fn(),
    setRouteTemplateActive: vi.fn(),
    setCrewTemplateActive: vi.fn(),
  }
})

const school: School = { id: 1, name: 'Riverside Elementary', location_lat: 0, location_lon: 0 }
const driver: Driver = {
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
const lift: Qualification = {
  id: 1,
  code: 'lift',
  kind: 'vehicle_capability',
  description: null,
  is_active: true,
}

const routeTemplate: RouteTemplate = {
  id: 7,
  school_id: 1,
  direction: 'am',
  window_earliest: 360,
  window_latest: 450,
  duration_minutes: 40,
  buffer_minutes: 10,
  days_of_week: [0, 1, 2, 3, 4],
  active_from: null,
  active_until: '2026-12-18',
  is_active: true,
  required_qualifications: [],
}
const crewTemplate: CrewTemplate = {
  id: 8,
  driver_id: 2,
  vehicle_id: 3,
  available_window_earliest: 300,
  available_window_latest: 900,
  days_of_week: [0, 2, 4],
  active_from: null,
  active_until: null,
  is_active: false,
}

function mockLoad() {
  vi.mocked(api.getRouteTemplates).mockResolvedValue([routeTemplate])
  vi.mocked(api.getCrewTemplates).mockResolvedValue([crewTemplate])
  vi.mocked(api.getSchools).mockResolvedValue([school])
  vi.mocked(api.getDrivers).mockResolvedValue([driver])
  vi.mocked(api.getVehicles).mockResolvedValue([vehicle])
  vi.mocked(api.getQualifications).mockResolvedValue([lift])
  vi.mocked(api.getStops).mockResolvedValue([])
}

describe('TemplatesPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockLoad()
  })

  it('lists route and crew templates with joined names, weekdays, and status', async () => {
    render(<TemplatesPage />)

    const routeSection = (await screen.findByRole('heading', { name: 'Route templates' }))
      .parentElement as HTMLElement
    await within(routeSection).findByText('Riverside Elementary', { selector: 'td' })
    expect(within(routeSection).getByText('Mon, Tue, Wed, Thu, Fri')).toBeInTheDocument()
    expect(within(routeSection).getByText('06:00–07:30')).toBeInTheDocument()
    expect(within(routeSection).getByText('… → 2026-12-18')).toBeInTheDocument()
    expect(within(routeSection).getByText('Active')).toBeInTheDocument()

    const crewSection = screen.getByRole('heading', { name: 'Crew templates' })
      .parentElement as HTMLElement
    expect(within(crewSection).getByText('Jordan Driver', { selector: 'td' })).toBeInTheDocument()
    expect(within(crewSection).getByText('Bus 101', { selector: 'td' })).toBeInTheDocument()
    expect(within(crewSection).getByText('Mon, Wed, Fri')).toBeInTheDocument()
    expect(within(crewSection).getByText('Inactive')).toBeInTheDocument()
  })

  it('creates a route template with the selected weekdays, range, and capabilities', async () => {
    vi.mocked(api.createRouteTemplate).mockResolvedValue(routeTemplate)
    const user = userEvent.setup()
    render(<TemplatesPage />)
    await screen.findByRole('option', { name: 'Riverside Elementary' })

    await user.selectOptions(screen.getByLabelText('School'), '1')
    await user.selectOptions(screen.getByLabelText('Direction'), 'pm')
    await user.type(screen.getByLabelText('Window start (minute of day)'), '900')
    await user.type(screen.getByLabelText('Window end (minute of day)'), '990')
    await user.type(screen.getByLabelText('Duration (minutes)'), '40')
    await user.clear(screen.getByLabelText('Buffer (minutes)'))
    await user.type(screen.getByLabelText('Buffer (minutes)'), '10')
    // Default Mon-Fri; drop Friday, add Saturday (first day picker = route form).
    await user.click(screen.getAllByLabelText('Fri')[0])
    await user.click(screen.getAllByLabelText('Sat')[0])
    await user.type(screen.getAllByLabelText('Active until (optional)')[0], '2026-12-18')
    await user.click(screen.getByLabelText('lift'))
    await user.click(screen.getByRole('button', { name: 'Add route template' }))

    await waitFor(() =>
      expect(api.createRouteTemplate).toHaveBeenCalledWith({
        school_id: 1,
        direction: 'pm',
        window_earliest: 900,
        window_latest: 990,
        duration_minutes: 40,
        buffer_minutes: 10,
        days_of_week: [0, 1, 2, 3, 5],
        active_from: null,
        active_until: '2026-12-18',
        required_qualification_codes: ['lift'],
      }),
    )
  })

  it('shows the API error when creating a route template fails', async () => {
    vi.mocked(api.createRouteTemplate).mockRejectedValue(
      new ApiError(400, "duration_minutes + buffer_minutes exceeds the route's own window length"),
    )
    const user = userEvent.setup()
    render(<TemplatesPage />)
    await screen.findByRole('option', { name: 'Riverside Elementary' })

    await user.selectOptions(screen.getByLabelText('School'), '1')
    await user.type(screen.getByLabelText('Window start (minute of day)'), '900')
    await user.type(screen.getByLabelText('Window end (minute of day)'), '910')
    await user.type(screen.getByLabelText('Duration (minutes)'), '40')
    await user.click(screen.getByRole('button', { name: 'Add route template' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('exceeds the route')
  })

  it('disables submit when no weekday is selected', async () => {
    const user = userEvent.setup()
    render(<TemplatesPage />)
    await screen.findByRole('option', { name: 'Riverside Elementary' })

    for (const day of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']) {
      await user.click(screen.getAllByLabelText(day)[0])
    }

    expect(screen.getByRole('button', { name: 'Add route template' })).toBeDisabled()
  })

  it('creates a crew template', async () => {
    vi.mocked(api.createCrewTemplate).mockResolvedValue(crewTemplate)
    const user = userEvent.setup()
    render(<TemplatesPage />)
    await screen.findByRole('option', { name: 'Jordan Driver' })

    const crewForm = screen.getByRole('button', { name: 'Add crew template' }).closest('form')
    expect(crewForm).not.toBeNull()
    await user.selectOptions(within(crewForm as HTMLElement).getByLabelText('Driver'), '2')
    await user.selectOptions(within(crewForm as HTMLElement).getByLabelText('Vehicle'), '3')
    await user.click(screen.getByRole('button', { name: 'Add crew template' }))

    await waitFor(() =>
      expect(api.createCrewTemplate).toHaveBeenCalledWith({
        driver_id: 2,
        vehicle_id: 3,
        available_window_earliest: 0,
        available_window_latest: 1439,
        days_of_week: [0, 1, 2, 3, 4],
        active_from: null,
        active_until: null,
      }),
    )
  })

  it('deactivates an active route template and reactivates an inactive crew template', async () => {
    vi.mocked(api.setRouteTemplateActive).mockResolvedValue({ ...routeTemplate, is_active: false })
    vi.mocked(api.setCrewTemplateActive).mockResolvedValue({ ...crewTemplate, is_active: true })
    const user = userEvent.setup()
    render(<TemplatesPage />)

    await user.click(await screen.findByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(api.setRouteTemplateActive).toHaveBeenCalledWith(7, false))

    await user.click(screen.getByRole('button', { name: 'Reactivate' }))
    await waitFor(() => expect(api.setCrewTemplateActive).toHaveBeenCalledWith(8, true))
  })

  it('shows a load error', async () => {
    vi.mocked(api.getRouteTemplates).mockRejectedValue(new ApiError(403, 'Forbidden'))
    render(<TemplatesPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden')
  })

  it("shows each route's stops and opens the stop editor", async () => {
    vi.mocked(api.getRouteTemplates).mockResolvedValue([
      {
        ...(await api.getRouteTemplates())[0],
        stops: [
          {
            position: 1,
            stop_id: 5,
            stop_label: 'Elm',
            location_lat: 29.71,
            location_lon: -95.41,
            minutes_from_start: 0,
          },
          {
            position: 2,
            stop_id: 6,
            stop_label: 'Oak',
            location_lat: 29.72,
            location_lon: -95.42,
            minutes_from_start: 6,
          },
        ],
      },
    ])
    render(<TemplatesPage />)
    expect(await screen.findByText('Elm → Oak')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit stops' }))
    expect(await screen.findByRole('heading', { name: /Stops in order/ })).toBeInTheDocument()
  })
})
