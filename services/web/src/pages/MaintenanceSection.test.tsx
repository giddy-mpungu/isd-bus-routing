import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { DefectReport, Vehicle, VehicleMaintenance } from '../api/types'
import { axeViolations } from '../test/axe'
import { MaintenanceSection } from './MaintenanceSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getMaintenanceDue: vi.fn(),
    getDefectReports: vi.fn(),
    getMaintenanceWindows: vi.fn(),
    getVehicleMaintenance: vi.fn(),
    createMaintenanceWindow: vi.fn(),
    endMaintenanceWindow: vi.fn(),
    takeOutOfServiceForDefect: vi.fn(),
    markDefectFixed: vi.fn(),
    setVehicleMaintenanceDates: vi.fn(),
    addServiceRecord: vi.fn(),
  }
})

const vehicles = [
  { id: 1, label: 'Bus 1', is_active: true },
  { id: 2, label: 'Bus 2', is_active: true },
  { id: 3, label: 'Retired', is_active: false },
] as Vehicle[]

const bus1: VehicleMaintenance = {
  vehicle_id: 1,
  vehicle_label: 'Bus 1',
  service_due_on: '2026-10-30',
  inspection_expires_on: '2027-06-30',
  service_log: [
    {
      id: 5,
      vehicle_id: 1,
      performed_on: '2026-09-01',
      work: 'Oil and filters',
      performed_by: 'Fleet shop',
      created_at: '2026-09-01T10:00:00Z',
    },
  ],
  windows: [],
}

const defect: DefectReport = {
  id: 7,
  driver_id: 4,
  vehicle_id: 2,
  service_date: '2026-10-15',
  report_type: 'vehicle_defect',
  description: 'Brakes squeal',
  created_at: '2026-10-15T12:00:00Z',
  status: 'open',
  resolution_note: null,
  driver_name: 'Jordan Driver',
  vehicle_label: 'Bus 2',
}

// Every state these tests reach is checked against WCAG 2.1 A/AA.
afterEach(async () => {
  expect(await axeViolations()).toEqual([])
})

describe('MaintenanceSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getMaintenanceDue).mockResolvedValue([
      {
        vehicle_id: 1,
        vehicle_label: 'Bus 1',
        severity: 'warning',
        message: "Bus 1's service is due on 2026-10-30",
      },
    ])
    vi.mocked(api.getDefectReports).mockResolvedValue([defect])
    vi.mocked(api.getMaintenanceWindows).mockResolvedValue([
      {
        id: 3,
        vehicle_id: 1,
        vehicle_label: 'Bus 1',
        kind: 'repair',
        starts_at: '2026-10-15T06:00:00',
        ends_at: null,
        reason: 'Alternator',
        driver_report_id: null,
        current: true,
      },
    ])
    vi.mocked(api.getVehicleMaintenance).mockResolvedValue(bus1)
  })

  it('shows what is due, the open defects, the windows and a bus record', async () => {
    render(<MaintenanceSection vehicles={vehicles} />)
    expect(await screen.findByText("Bus 1's service is due on 2026-10-30")).toBeInTheDocument()
    expect(screen.getByText(/Brakes squeal/)).toBeInTheDocument()
    const windows = screen.getByRole('table', { name: 'Maintenance windows' })
    expect(within(windows).getByText('Out now')).toBeInTheDocument()
    expect(within(windows).getByText('until marked back in service')).toBeInTheDocument()
    expect(await screen.findByText('2026-09-01: Oil and filters (Fleet shop)')).toBeInTheDocument()
    expect(screen.getByLabelText('Next service due')).toHaveValue('2026-10-30')
    // Retired buses aren't offered.
    expect(screen.queryByRole('option', { name: 'Retired' })).not.toBeInTheDocument()
  })

  it('takes a bus out of service from a defect report', async () => {
    vi.mocked(api.takeOutOfServiceForDefect).mockResolvedValue({
      ...defect,
      status: 'out_of_service',
    })
    const user = userEvent.setup()
    render(<MaintenanceSection vehicles={vehicles} />)
    await user.click(
      await screen.findByRole('button', { name: 'Take Bus 2 out of service (report 7)' }),
    )
    await user.click(screen.getByRole('button', { name: 'Take it out now' }))
    await waitFor(() => expect(api.takeOutOfServiceForDefect).toHaveBeenCalledWith(7, null))
    expect(await screen.findByRole('status')).toHaveTextContent('Bus 2 is out of service from now')
  })

  it('marks a defect fixed with a note', async () => {
    vi.mocked(api.markDefectFixed).mockResolvedValue({ ...defect, status: 'fixed' })
    const user = userEvent.setup()
    render(<MaintenanceSection vehicles={vehicles} />)
    await user.click(await screen.findByRole('button', { name: 'Mark report 7 fixed' }))
    await user.type(screen.getByLabelText('What was done (optional)'), 'Pads replaced')
    await user.click(screen.getByRole('button', { name: 'Mark fixed' }))
    await waitFor(() => expect(api.markDefectFixed).toHaveBeenCalledWith(7, 'Pads replaced'))
  })

  it('adds a maintenance window and puts a bus back in service', async () => {
    vi.mocked(api.createMaintenanceWindow).mockResolvedValue({
      id: 4,
      vehicle_id: 2,
      vehicle_label: 'Bus 2',
      kind: 'planned',
      starts_at: '2026-10-20T06:00:00',
      ends_at: null,
      reason: 'Annual service',
      driver_report_id: null,
      current: false,
    })
    const user = userEvent.setup()
    render(<MaintenanceSection vehicles={vehicles} />)
    await screen.findByRole('table', { name: 'Maintenance windows' })
    await user.selectOptions(screen.getByLabelText('Bus'), '2')
    await user.type(screen.getByLabelText('From'), '2026-10-20T06:00')
    await user.type(screen.getByLabelText('Reason'), 'Annual service')
    await user.click(screen.getByRole('button', { name: 'Add maintenance window' }))
    await waitFor(() =>
      expect(api.createMaintenanceWindow).toHaveBeenCalledWith({
        vehicle_id: 2,
        kind: 'planned',
        starts_at: '2026-10-20T06:00',
        ends_at: null,
        reason: 'Annual service',
      }),
    )

    await user.click(screen.getByRole('button', { name: 'Bus 1 back in service' }))
    await waitFor(() => expect(api.endMaintenanceWindow).toHaveBeenCalledWith(3))
  })

  it('logs service and moves the next due date', async () => {
    vi.mocked(api.addServiceRecord).mockResolvedValue(bus1)
    const user = userEvent.setup()
    render(<MaintenanceSection vehicles={vehicles} />)
    await screen.findByText('2026-09-01: Oil and filters (Fleet shop)')
    await user.type(screen.getByLabelText('Done on'), '2026-10-15')
    await user.type(screen.getByLabelText('Work done'), 'Brake pads')
    await user.type(screen.getByLabelText('Done by'), 'Fleet shop')
    await user.type(screen.getByLabelText('Next service due (optional)'), '2027-01-15')
    await user.click(screen.getByRole('button', { name: 'Log service for Bus 1' }))
    await waitFor(() =>
      expect(api.addServiceRecord).toHaveBeenCalledWith(1, {
        performed_on: '2026-10-15',
        work: 'Brake pads',
        performed_by: 'Fleet shop',
        next_service_due_on: '2027-01-15',
      }),
    )
  })
})
