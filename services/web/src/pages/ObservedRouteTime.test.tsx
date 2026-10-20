import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { RouteTemplate } from '../api/types'
import { axeViolations } from '../test/axe'
import { ObservedRouteTime } from './ObservedRouteTime'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getObservedRunDuration: vi.fn(), setRouteTemplateDuration: vi.fn() }
})

const route = {
  id: 4,
  school_id: 2,
  direction: 'am',
  duration_minutes: 40,
} as RouteTemplate

describe('ObservedRouteTime', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  afterEach(async () => {
    expect(await axeViolations()).toEqual([])
  })

  it("shows the route's observed time and plans with it on request", async () => {
    vi.mocked(api.getObservedRunDuration).mockResolvedValue({
      sample_count: 3,
      average_actual_minutes: 47.6,
      most_recent_actual_minutes: 50,
      most_recent_service_date: '2026-09-04',
    })
    vi.mocked(api.setRouteTemplateDuration).mockResolvedValue({ ...route, duration_minutes: 48 })
    const changed = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<ObservedRouteTime template={route} onChanged={changed} />)

    await user.click(screen.getByRole('button', { name: 'Observed time' }))
    expect(await screen.findByText(/Took 48 min on average over 3 runs/)).toBeInTheDocument()
    expect(api.getObservedRunDuration).toHaveBeenCalledWith(2, 'am', 4)
    await user.click(screen.getByRole('button', { name: 'Plan 48 minutes' }))
    await waitFor(() => expect(api.setRouteTemplateDuration).toHaveBeenCalledWith(4, 48))
    expect(changed).toHaveBeenCalled()
  })

  it('says so when the route has no completed runs yet', async () => {
    vi.mocked(api.getObservedRunDuration).mockResolvedValue({
      sample_count: 0,
      average_actual_minutes: null,
      most_recent_actual_minutes: null,
      most_recent_service_date: null,
    })
    const user = userEvent.setup()
    render(<ObservedRouteTime template={route} onChanged={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'Observed time' }))
    expect(await screen.findByText('No completed runs on this route yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Plan/ })).not.toBeInTheDocument()
  })
})
