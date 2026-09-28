import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { DispatchTask, Driver, Vehicle } from '../api/types'
import { DispatchTasksSection } from './DispatchTasksSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getDispatchTasks: vi.fn(),
    createDispatchTask: vi.fn(),
    cancelDispatchTask: vi.fn(),
  }
})

const DAY = '2026-10-08'

function driver(id: number, full_name: string, is_active = true): Driver {
  return {
    id,
    full_name,
    max_continuous_minutes: null,
    license_class: 'cdl_b',
    is_active,
    qualifications: [],
  }
}

const vehicle = { id: 30, label: 'Bus 30', is_active: true } as Vehicle
const retired = { id: 31, label: 'Bus 31', is_active: false } as Vehicle

const task: DispatchTask = {
  id: 4,
  kind: 'emergency',
  service_date: DAY,
  start_minute: 400,
  end_minute: 470,
  driver_id: 1,
  driver_full_name: 'Pat Driver',
  vehicle_id: 30,
  vehicle_label: 'Bus 30',
  location: 'Oak St & 5th Ave',
  instructions: 'Go now.',
  status: 'acknowledged',
  cancelled: false,
  created_at: '2026-10-08T06:00:00Z',
  routes_needing_cover: ['Riverside AM run on Bus 30 (07:00-07:30)'],
}

function renderSection(onChanged = vi.fn()) {
  render(
    <DispatchTasksSection
      serviceDate={DAY}
      drivers={[driver(1, 'Pat Driver'), driver(2, 'Gone Driver', false)]}
      vehicles={[vehicle, retired]}
      onChanged={onChanged}
    />,
  )
  return onChanged
}

describe('DispatchTasksSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getDispatchTasks).mockResolvedValue([])
  })

  it('lists the day’s tasks with their state and the runs they need covered', async () => {
    vi.mocked(api.getDispatchTasks).mockResolvedValue([task])
    renderSection()

    expect(await screen.findByText('Respond to an emergency')).toBeInTheDocument()
    expect(api.getDispatchTasks).toHaveBeenCalledWith(DAY)
    expect(screen.getByText('Acknowledged')).toBeInTheDocument()
    expect(
      screen.getByText('Needs cover: Riverside AM run on Bus 30 (07:00-07:30)'),
    ).toBeInTheDocument()
  })

  it('only offers active drivers and vehicles', async () => {
    renderSection()
    await screen.findByText('No dispatch tasks for this date.')
    expect(screen.getByRole('option', { name: 'Pat Driver' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Gone Driver' })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Bus 30' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Bus 31' })).not.toBeInTheDocument()
  })

  it('sends a task with times as minutes of the day and reloads the schedule', async () => {
    vi.mocked(api.createDispatchTask).mockResolvedValue(task)
    const onChanged = renderSection()
    await screen.findByText('No dispatch tasks for this date.')
    const user = userEvent.setup()

    await user.selectOptions(screen.getByLabelText('Task'), 'emergency')
    await user.selectOptions(screen.getByLabelText('Assign to driver'), '1')
    await user.type(screen.getByLabelText('Start time'), '06:40')
    await user.type(screen.getByLabelText('End time'), '07:50')
    await user.type(screen.getByLabelText('Where (optional)'), '  Oak St & 5th Ave ')
    await user.type(screen.getByLabelText('Instructions for the driver'), 'Go now.')
    await user.click(screen.getByRole('button', { name: 'Send to driver' }))

    await waitFor(() =>
      expect(api.createDispatchTask).toHaveBeenCalledWith({
        kind: 'emergency',
        service_date: DAY,
        start_minute: 400,
        end_minute: 470,
        driver_id: 1,
        vehicle_id: null,
        location: 'Oak St & 5th Ave',
        instructions: 'Go now.',
      }),
    )
    expect(
      await screen.findByText(
        'Task #4 sent to Pat Driver. These runs now need cover: Riverside AM run on Bus 30 (07:00-07:30).',
      ),
    ).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
    expect(api.getDispatchTasks).toHaveBeenCalledTimes(2)
  })

  it('shows why the server refused a task', async () => {
    vi.mocked(api.createDispatchTask).mockRejectedValue(
      new ApiError(409, 'Cannot assign this task: Driver Pat Driver is absent'),
    )
    const onChanged = renderSection()
    await screen.findByText('No dispatch tasks for this date.')
    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Assign to driver'), '1')
    await user.type(screen.getByLabelText('Start time'), '09:00')
    await user.type(screen.getByLabelText('End time'), '10:00')
    await user.type(screen.getByLabelText('Instructions for the driver'), 'Go.')
    await user.click(screen.getByRole('button', { name: 'Send to driver' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Cannot assign this task: Driver Pat Driver is absent',
    )
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('cancels a task after confirming, then reloads', async () => {
    vi.mocked(api.getDispatchTasks).mockResolvedValue([task])
    vi.mocked(api.cancelDispatchTask).mockResolvedValue({ ...task, cancelled: true })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onChanged = renderSection()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Cancel task' }))

    expect(confirm).toHaveBeenCalledWith('Cancel task #4 for Pat Driver?')
    await waitFor(() => expect(api.cancelDispatchTask).toHaveBeenCalledWith(4))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    confirm.mockRestore()
  })

  it('offers no cancel for a cancelled or completed task', async () => {
    vi.mocked(api.getDispatchTasks).mockResolvedValue([
      { ...task, cancelled: true },
      { ...task, id: 5, status: 'completed' },
    ])
    renderSection()
    expect(await screen.findByText('Cancelled')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel task' })).not.toBeInTheDocument()
  })
})
