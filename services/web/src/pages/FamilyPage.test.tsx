import { render, screen, waitFor } from '@testing-library/react'
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

  it('locating the AM bus shows driver/vehicle/coordinates when available', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    const position: BusPosition = {
      available: true,
      ambiguous: false,
      location_lat: 29.71,
      location_lon: -95.41,
      recorded_at: '2026-09-01T12:00:00Z',
      driver_full_name: 'Jordan Driver',
      vehicle_label: 'Bus 101',
    }
    vi.mocked(api.getBusPosition).mockResolvedValue(position)
    render(<FamilyPage />)
    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getAllByRole('button', { name: 'Locate bus' })[0])

    expect(api.getBusPosition).toHaveBeenCalledWith(10, today(), 'am')
    await waitFor(() => expect(screen.getByText(/Jordan Driver, Bus 101/)).toBeInTheDocument())
  })

  it('locating the bus shows an ambiguous notice when multiple runs share the leg', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    vi.mocked(api.getBusPosition).mockResolvedValue({
      available: false,
      ambiguous: true,
      location_lat: null,
      location_lon: null,
      recorded_at: null,
      driver_full_name: null,
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
})
