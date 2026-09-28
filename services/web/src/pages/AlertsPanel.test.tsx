import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { DayAlerts } from '../api/types'
import { AlertsPanel } from './AlertsPanel'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getAlerts: vi.fn() }
})

const DAY = '2026-08-01'

const day: DayAlerts = {
  service_date: DAY,
  district_time: '07:25',
  alerts: [
    {
      kind: 'needs_cover',
      severity: 'critical',
      message: 'Needs cover: Riverside AM run on Bus 7 (07:30-08:00): driver absent',
      entity_type: 'assignment',
      entity_id: 3,
      minute: 450,
    },
    {
      kind: 'not_acknowledged',
      severity: 'warning',
      message: "Sam hasn't acknowledged Northside AM run, starting at 07:45",
      entity_type: 'assignment',
      entity_id: 4,
      minute: 465,
    },
  ],
}

describe('AlertsPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('lists alerts most urgent first, with counts and the district time', async () => {
    vi.mocked(api.getAlerts).mockResolvedValue(day)
    render(<AlertsPanel serviceDate={DAY} refreshToken={0} />)

    expect(await screen.findByText(/Needs cover: Riverside AM run/)).toBeInTheDocument()
    expect(api.getAlerts).toHaveBeenCalledWith(DAY)
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items[0]).toMatch(/^Critical Needs cover/)
    expect(items[1]).toMatch(/^Warning Sam hasn't acknowledged/)
    expect(screen.getByText('1 critical')).toBeInTheDocument()
    expect(screen.getByText('1 warning')).toBeInTheDocument()
    expect(screen.getByText('As of 07:25 district time.')).toBeInTheDocument()
  })

  it('says so when nothing needs attention', async () => {
    vi.mocked(api.getAlerts).mockResolvedValue({ ...day, alerts: [] })
    render(<AlertsPanel serviceDate={DAY} refreshToken={0} />)
    expect(await screen.findByText('Nothing needs attention.')).toBeInTheDocument()
    expect(screen.queryByText(/critical$/)).not.toBeInTheDocument()
  })

  it('shows a load error', async () => {
    vi.mocked(api.getAlerts).mockRejectedValue(new ApiError(403, 'Not allowed'))
    render(<AlertsPanel serviceDate={DAY} refreshToken={0} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Not allowed')
    expect(screen.queryByText('Nothing needs attention.')).not.toBeInTheDocument()
  })

  it('checks again when the schedule reloads', async () => {
    vi.mocked(api.getAlerts).mockResolvedValue(day)
    const { rerender } = render(<AlertsPanel serviceDate={DAY} refreshToken={0} />)
    await waitFor(() => expect(api.getAlerts).toHaveBeenCalledTimes(1))
    rerender(<AlertsPanel serviceDate={DAY} refreshToken={1} />)
    await waitFor(() => expect(api.getAlerts).toHaveBeenCalledTimes(2))
  })

  it('refreshes every minute', async () => {
    vi.useFakeTimers()
    vi.mocked(api.getAlerts).mockResolvedValue(day)
    render(<AlertsPanel serviceDate={DAY} refreshToken={0} />)
    expect(api.getAlerts).toHaveBeenCalledTimes(1)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(api.getAlerts).toHaveBeenCalledTimes(2)
  })

  it("doesn't show another date's alerts while the new date loads", async () => {
    vi.mocked(api.getAlerts).mockResolvedValue(day)
    const { rerender } = render(<AlertsPanel serviceDate={DAY} refreshToken={0} />)
    expect(await screen.findByText(/Needs cover/)).toBeInTheDocument()
    vi.mocked(api.getAlerts).mockReturnValue(new Promise(() => undefined))
    rerender(<AlertsPanel serviceDate="2026-08-02" refreshToken={0} />)
    expect(screen.queryByText(/Needs cover/)).not.toBeInTheDocument()
  })
})
