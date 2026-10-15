import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { BellChange, School, SchoolBells } from '../api/types'
import { axeViolations } from '../test/axe'
import { BellSchedulesSection } from './BellSchedulesSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getBellRules: vi.fn(),
    updateBellRules: vi.fn(),
    getSchoolBells: vi.fn(),
    setSchoolBellOffsets: vi.fn(),
    createBellSchedule: vi.fn(),
    updateBellSchedule: vi.fn(),
    deleteBellSchedule: vi.fn(),
    getBellCalendar: vi.fn(),
    setBellCalendarDay: vi.fn(),
    deleteBellCalendarDay: vi.fn(),
    importBellSchedules: vi.fn(),
  }
})

const schools: School[] = [
  { id: 1, name: 'Riverside Elementary', location_lat: 29.7, location_lon: -95.4 },
  { id: 2, name: 'North High', location_lat: 29.8, location_lon: -95.5 },
] as School[]

const offsets = {
  arrive_earliest_before: 25,
  arrive_latest_before: 10,
  leave_earliest_after: 5,
  leave_latest_after: 15,
}

const riverside: SchoolBells = {
  school_id: 1,
  school_name: 'Riverside Elementary',
  schedules: [
    {
      id: 11,
      school_id: 1,
      name: 'Early release',
      first_bell_minute: 480,
      dismissal_minute: 720,
      is_regular: false,
    },
    {
      id: 10,
      school_id: 1,
      name: 'Regular',
      first_bell_minute: 480,
      dismissal_minute: 900,
      is_regular: true,
    },
  ],
  own_offsets: null,
  offsets_in_use: offsets,
  upcoming_days: [],
}

const change: BellChange = { runs_updated: 2, assigned_runs_moved: 1, skipped_schools: [] }

// Every state these tests reach is checked against WCAG 2.1 A/AA.
afterEach(async () => {
  expect(await axeViolations()).toEqual([])
})

describe('BellSchedulesSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getBellRules).mockResolvedValue({ ...offsets, is_default: true })
    vi.mocked(api.getSchoolBells).mockResolvedValue(riverside)
    vi.mocked(api.getBellCalendar).mockResolvedValue([])
  })

  it("shows the first school's bells as clock times", async () => {
    render(<BellSchedulesSection schools={schools} canEdit />)
    const table = await screen.findByRole('table', {
      name: 'Bell schedules at Riverside Elementary',
    })
    const regular = within(table).getByRole('row', { name: /Regular/ })
    expect(regular).toHaveTextContent('08:00')
    expect(regular).toHaveTextContent('15:00')
    expect(within(table).getByRole('row', { name: /Early release/ })).toHaveTextContent('12:00')
    expect(
      screen.getAllByLabelText('Arrive at the earliest (minutes before the first bell)')[0],
    ).toHaveValue(25)
  })

  it('edits a schedule and says what moved', async () => {
    vi.mocked(api.updateBellSchedule).mockResolvedValue(change)
    const user = userEvent.setup()
    render(<BellSchedulesSection schools={schools} canEdit />)
    await user.click(await screen.findByRole('button', { name: 'Edit Regular' }))
    const first = screen.getByLabelText('Regular: first bell')
    await user.clear(first)
    await user.type(first, '08:30')
    await user.click(screen.getByRole('button', { name: 'Save Regular' }))

    await waitFor(() =>
      expect(api.updateBellSchedule).toHaveBeenCalledWith(10, {
        first_bell_minute: 510,
        dismissal_minute: 900,
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent(
      '2 upcoming runs moved to the new bell times. 1 of them already had a bus',
    )
  })

  it('adds a schedule in clock times', async () => {
    vi.mocked(api.createBellSchedule).mockResolvedValue(riverside.schedules[0])
    const user = userEvent.setup()
    render(<BellSchedulesSection schools={schools} canEdit />)
    await screen.findByRole('button', { name: 'Edit Regular' })
    await user.type(screen.getByLabelText('Name (e.g. Regular, Early release)'), 'Late start')
    const add = screen.getByRole('button', { name: 'Add schedule' }).closest('form') as HTMLElement
    await user.type(within(add).getByLabelText('First bell'), '10:00')
    await user.type(within(add).getByLabelText('Dismissal'), '15:00')
    await user.click(screen.getByRole('button', { name: 'Add schedule' }))
    await waitFor(() =>
      expect(api.createBellSchedule).toHaveBeenCalledWith(1, {
        name: 'Late start',
        first_bell_minute: 600,
        dismissal_minute: 900,
      }),
    )
  })

  it('marks an early-release day for every school with that schedule', async () => {
    vi.mocked(api.setBellCalendarDay).mockResolvedValue({
      ...change,
      skipped_schools: [],
    })
    const user = userEvent.setup()
    render(<BellSchedulesSection schools={schools} canEdit />)
    await screen.findByRole('button', { name: 'Edit Regular' })
    await user.type(screen.getByLabelText('Date'), '2026-10-30')
    await user.type(screen.getByLabelText('Schedule to use'), 'Early release')
    await user.click(screen.getByRole('button', { name: 'Mark the day' }))
    await waitFor(() =>
      expect(api.setBellCalendarDay).toHaveBeenCalledWith('2026-10-30', 'Early release', null),
    )
  })

  it('gives a school its own windows, and back', async () => {
    vi.mocked(api.setSchoolBellOffsets).mockResolvedValue(change)
    const user = userEvent.setup()
    render(<BellSchedulesSection schools={schools} canEdit />)
    const useDistrict = await screen.findByLabelText("Use the district's bus windows")
    expect(useDistrict).toBeChecked()
    await user.click(useDistrict)
    const own = screen
      .getByRole('button', { name: "Save Riverside Elementary's windows" })
      .closest('form') as HTMLElement
    const earliest = within(own).getByLabelText(
      'Arrive at the earliest (minutes before the first bell)',
    )
    await user.clear(earliest)
    await user.type(earliest, '30')
    await user.click(within(own).getByRole('button', { name: /windows/ }))
    await waitFor(() =>
      expect(api.setSchoolBellOffsets).toHaveBeenCalledWith(1, {
        ...offsets,
        arrive_earliest_before: 30,
      }),
    )
  })

  it('previews a CSV before importing it', async () => {
    vi.mocked(api.importBellSchedules)
      .mockResolvedValueOnce({
        applied: false,
        rows: [
          {
            line: 2,
            school: 'North High',
            schedule: 'Regular',
            outcome: 'created',
            message: null,
          },
          {
            line: 3,
            school: 'Nowhere',
            schedule: 'Regular',
            outcome: 'error',
            message: 'No school by that name',
          },
        ],
        change: null,
      })
      .mockResolvedValueOnce({ applied: true, rows: [], change })
    const user = userEvent.setup()
    render(<BellSchedulesSection schools={schools} canEdit />)
    await screen.findByRole('button', { name: 'Edit Regular' })
    await user.type(
      screen.getByLabelText('Or paste it'),
      'school,schedule,first_bell,dismissal{enter}North High,Regular,07:30,14:45',
    )
    await user.click(screen.getByRole('button', { name: 'Preview' }))
    const preview = await screen.findByRole('table', { name: 'Preview: nothing saved yet' })
    expect(preview).toHaveTextContent('error: No school by that name')
    expect(api.importBellSchedules).toHaveBeenLastCalledWith(expect.any(String), false)

    await user.click(screen.getByRole('button', { name: 'Import these bell times' }))
    await waitFor(() =>
      expect(api.importBellSchedules).toHaveBeenLastCalledWith(expect.any(String), true),
    )
  })

  it('is read-only for dispatchers', async () => {
    render(<BellSchedulesSection schools={schools} canEdit={false} />)
    await screen.findByRole('table', { name: 'Bell schedules at Riverside Elementary' })
    expect(screen.queryByRole('button', { name: 'Edit Regular' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add schedule' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mark the day' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Or paste it')).not.toBeInTheDocument()
  })
})
