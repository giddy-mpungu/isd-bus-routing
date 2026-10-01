import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { RoadClosure, School } from '../api/types'
import { RoadClosuresSection } from './RoadClosuresSection'
import { findMap } from '../test/map'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getRoadClosures: vi.fn(),
    createRoadClosure: vi.fn(),
    clearRoadClosure: vi.fn(),
  }
})

const schools: School[] = [{ id: 1, name: 'Riverside', location_lat: 29.7, location_lon: -95.4 }]

const crash: RoadClosure = {
  id: 3,
  kind: 'collision',
  note: 'Two-car crash on Oak St',
  location_lat: 29.725,
  location_lon: -95.4,
  radius_m: 150,
  starts_at: '2026-10-05T12:00:00Z',
  ends_at: null,
  cleared: false,
  active: true,
  affected_runs: [
    { assignment_id: 9, description: 'Riverside AM run on Bus 7', stop_inside: null },
    { assignment_id: 10, description: 'Riverside AM run on Bus 8', stop_inside: 'Oak & 5th' },
  ],
}

describe('RoadClosuresSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getRoadClosures).mockResolvedValue([crash])
  })

  it('lists closures in force with the runs they affect, and maps them', async () => {
    render(<RoadClosuresSection schools={schools} />)
    expect(await screen.findByText(/Two-car crash on Oak St/)).toBeInTheDocument()
    expect(screen.getByText('In force')).toBeInTheDocument()
    expect(screen.getByText(/150 m, until cleared/)).toBeInTheDocument()
    expect(screen.getByText('Riverside AM run on Bus 7')).toBeInTheDocument()
    expect(
      screen.getByText('⚠ Riverside AM run on Bus 8: the Oak & 5th stop is inside it'),
    ).toBeInTheDocument()
    const map = await findMap('Road closures map')
    expect(within(map).getByTitle('Collision')).toBeInTheDocument()
    expect(map.querySelector('.map-pin-closure')).not.toBeNull()
  })

  it('records a closure where the map was clicked', async () => {
    vi.mocked(api.createRoadClosure).mockResolvedValue(crash)
    render(<RoadClosuresSection schools={schools} />)
    const user = userEvent.setup()
    const submit = await screen.findByRole('button', { name: 'Click the map first' })
    expect(submit).toBeDisabled()

    fireEvent.click(await findMap('Road closures map'), {
      clientX: 5,
      clientY: 5,
    })
    await user.selectOptions(screen.getByLabelText('What'), 'flooding')
    await user.type(screen.getByLabelText('Details'), 'Underpass flooded')
    await user.clear(screen.getByLabelText('Area to avoid (metres around the spot)'))
    await user.type(screen.getByLabelText('Area to avoid (metres around the spot)'), '300')
    await user.click(screen.getByRole('button', { name: 'Record closure' }))

    await waitFor(() => expect(api.createRoadClosure).toHaveBeenCalled())
    const [body] = vi.mocked(api.createRoadClosure).mock.calls[0]
    expect(body).toMatchObject({
      kind: 'flooding',
      note: 'Underpass flooded',
      radius_m: 300,
      ends_at: null,
    })
    expect(Number.isFinite(body.location_lat) && Number.isFinite(body.location_lon)).toBe(true)
    expect(api.getRoadClosures).toHaveBeenCalledTimes(2)
  })

  it('clears a closure when the road is open again', async () => {
    vi.mocked(api.clearRoadClosure).mockResolvedValue({ ...crash, cleared: true, active: false })
    render(<RoadClosuresSection schools={schools} />)
    const user = userEvent.setup()
    vi.mocked(api.getRoadClosures).mockResolvedValue([])
    await user.click(await screen.findByRole('button', { name: 'Road is open again' }))
    await waitFor(() => expect(api.clearRoadClosure).toHaveBeenCalledWith(3))
    expect(await screen.findByText('No closures in force or coming up.')).toBeInTheDocument()
  })

  it('shows why recording failed', async () => {
    vi.mocked(api.createRoadClosure).mockRejectedValue(
      new ApiError(400, 'The end must be after the start'),
    )
    render(<RoadClosuresSection schools={schools} />)
    const user = userEvent.setup()
    fireEvent.click(await findMap('Road closures map'), {
      clientX: 5,
      clientY: 5,
    })
    await user.type(screen.getByLabelText('Details'), 'x')
    await user.click(screen.getByRole('button', { name: 'Record closure' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The end must be after the start')
  })
})
