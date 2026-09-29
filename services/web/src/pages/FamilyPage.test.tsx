import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { BusPosition, FamilyMember } from '../api/types'
import { FamilyPage } from './FamilyPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getMyFamily: vi.fn(),
    updateRidership: vi.fn(),
    getBusPosition: vi.fn(),
    getMyAnnouncements: vi.fn(),
  }
})

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

const child: FamilyMember = {
  student_id: 10,
  full_name: 'Jamie Student',
  school_name: 'Riverside Elementary',
  stop_label: 'Oak & 5th',
  service_date: today(),
  riding_am: true,
  riding_pm: true,
  am_changes_closed: null,
  pm_changes_closed: null,
}

describe('FamilyPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([])
  })

  it('renders a card per linked child with school/stop and ridership state', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    render(<FamilyPage />)

    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())
    expect(screen.getByText('Riverside Elementary')).toBeInTheDocument()
    expect(screen.getByText('Stop: Oak & 5th')).toBeInTheDocument()
    expect(screen.getByText('AM: Riding')).toBeInTheDocument()
    expect(screen.getByText('PM: Riding')).toBeInTheDocument()
  })

  it('renders transportation announcements for the family audience', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    vi.mocked(api.getMyAnnouncements).mockResolvedValue([
      {
        id: 1,
        message: 'Route 12 substitute driver today.',
        category: 'substitution',
        audience: 'family',
        school_id: null,
        created_at: '2026-09-14T12:00:00Z',
      },
    ])
    render(<FamilyPage />)

    await waitFor(() =>
      expect(screen.getByText(/Route 12 substitute driver today\./)).toBeInTheDocument(),
    )
  })

  it('shows a friendly message when there are no linked students', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([])
    render(<FamilyPage />)

    await waitFor(() => expect(screen.getByText('No linked students found.')).toBeInTheDocument())
  })

  it('toggling AM off calls updateRidership with is_riding false and refreshes', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    vi.mocked(api.updateRidership).mockResolvedValue(undefined)
    render(<FamilyPage />)
    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Mark not riding AM' }))

    await waitFor(() =>
      expect(api.updateRidership).toHaveBeenCalledWith(10, {
        service_date: today(),
        direction: 'am',
        is_riding: false,
      }),
    )
    expect(api.getMyFamily).toHaveBeenCalledTimes(2) // initial load + reload after PATCH
  })

  it('shows an error message when the ridership update fails', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    vi.mocked(api.updateRidership).mockRejectedValue(
      new ApiError(403, 'You can only declare ridership for your own family'),
    )
    render(<FamilyPage />)
    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Mark not riding AM' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('your own family'))
  })

  it('locating the AM bus shows the bus and its approximate position, never the driver', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    const position: BusPosition = {
      available: true,
      ambiguous: false,
      location_lat: 29.712,
      location_lon: -95.419,
      recorded_at: '2026-09-01T12:00:00Z',
      vehicle_label: 'Bus 101',
    }
    vi.mocked(api.getBusPosition).mockResolvedValue(position)
    render(<FamilyPage />)
    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getAllByRole('button', { name: 'Locate bus' })[0])

    expect(api.getBusPosition).toHaveBeenCalledWith(10, today(), 'am')
    await waitFor(() =>
      expect(screen.getByText(/Bus 101 was near 29\.712, -95\.419 at /)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/Jordan/)).not.toBeInTheDocument()
    const map = await screen.findByRole('region', { name: 'Approximate location of Bus 101' })
    expect(within(map).getByTitle('Bus 101 (approximate)')).toBeInTheDocument()
    expect(map.querySelector('.map-pin-approx')).not.toBeNull()
  })

  it('shows no map when the bus has no live position', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    vi.mocked(api.getBusPosition).mockResolvedValue({
      available: false,
      ambiguous: false,
      location_lat: null,
      location_lon: null,
      recorded_at: null,
      vehicle_label: 'Bus 101',
    })
    render(<FamilyPage />)
    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())
    const user = userEvent.setup()
    await user.click(screen.getAllByRole('button', { name: 'Locate bus' })[0])

    expect(await screen.findByText('No live position yet.')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /Approximate location/ })).not.toBeInTheDocument()
  })

  it('locating the bus shows an ambiguous notice when multiple runs share the leg', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    vi.mocked(api.getBusPosition).mockResolvedValue({
      available: false,
      ambiguous: true,
      location_lat: null,
      location_lon: null,
      recorded_at: null,
      vehicle_label: null,
    })
    render(<FamilyPage />)
    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getAllByRole('button', { name: 'Locate bus' })[0])

    await waitFor(() =>
      expect(
        screen.getByText(/more than one run serves this school\/leg today/),
      ).toBeInTheDocument(),
    )
  })

  it('a leg past the cutoff cannot be changed and says why', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([
      {
        ...child,
        am_changes_closed:
          "Changes to today's AM ride closed at 06:00. Please contact the transportation office.",
      },
    ])
    render(<FamilyPage />)

    expect(await screen.findByText(/AM ride closed at 06:00/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mark not riding AM' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Mark not riding PM' })).toBeEnabled()
  })

  it("shows when the bus is due at the child's stop today, and if that moved", async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([
      {
        ...child,
        am_eta: { stop_label: 'Oak & 5th', eta_minute: 428, planned_minute: 420, changed: true },
        pm_eta: { stop_label: 'Oak & 5th', eta_minute: 931, planned_minute: 930, changed: false },
      },
    ])
    render(<FamilyPage />)
    expect(
      await screen.findByText('Bus due at Oak & 5th around 07:08 (changed from 07:00 today)'),
    ).toBeInTheDocument()
    expect(screen.getByText('Bus due at Oak & 5th around 15:31')).toBeInTheDocument()
    expect(screen.getByText(/around 07:08/)).toHaveClass('is-changed')
  })

  it('shows no time when there is no estimate for a leg', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([{ ...child, am_eta: null, pm_eta: null }])
    render(<FamilyPage />)
    await screen.findByText('Jamie Student')
    expect(screen.queryByText(/Bus due at/)).not.toBeInTheDocument()
  })
})
