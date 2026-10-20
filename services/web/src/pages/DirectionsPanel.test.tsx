import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { DirectionsResult } from '../api/types'
import { DirectionsPanel } from './DirectionsPanel'
import { findMap } from '../test/map'
import { stubGeolocation } from '../test/geolocation'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getDirections: vi.fn(), getTripDirections: vi.fn() }
})

const waypoints = [
  { label: 'Far', lat: 29.74, lon: -95.4 },
  { label: 'Near', lat: 29.71, lon: -95.4 },
  { label: 'Riverside', lat: 29.7, lon: -95.4 },
]

const directions: DirectionsResult = {
  available: true,
  reason: null,
  waypoints,
  distance_m: 4828,
  duration_s: 600,
  coordinates: [
    [29.74, -95.4],
    [29.71, -95.4],
    [29.7, -95.4],
  ],
  legs: [
    { to_label: 'Near', distance_m: 3219, duration_s: 420 },
    { to_label: 'Riverside', distance_m: 1609, duration_s: 180 },
  ],
  steps: [
    {
      instruction: 'Head south on Oak Street',
      name: 'Oak Street',
      distance_m: 3219,
      duration_s: 420,
      leg: 0,
    },
    { instruction: 'Arrive at Near', name: '', distance_m: 0, duration_s: 0, leg: 0 },
    {
      instruction: 'Turn right onto School Road',
      name: 'School Road',
      distance_m: 1609,
      duration_s: 180,
      leg: 1,
    },
  ],
  attribution: 'Directions © openrouteservice.org | Map data © OpenStreetMap contributors',
}

async function open() {
  const user = userEvent.setup()
  render(<DirectionsPanel assignmentId={7} />)
  await user.click(screen.getByRole('button', { name: 'Directions' }))
  return user
}

describe('DirectionsPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows one leg at a time, in order, with the route on a map', async () => {
    vi.mocked(api.getDirections).mockResolvedValue(directions)
    const user = await open()
    expect(api.getDirections).toHaveBeenCalledWith(7, undefined)
    expect(
      await screen.findByRole('heading', { name: 'To Near (2.0 mi, 7 min)' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Whole route: 3.0 mi, about 10 min')).toBeInTheDocument()
    expect(
      Array.from(document.querySelectorAll('.directions-steps li')).map((li) => li.textContent),
    ).toEqual(['Head south on Oak Street 2.0 mi', 'Arrive at Near'])
    expect(screen.getByText(/openrouteservice/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Next stop' }))
    expect(
      screen.getByRole('heading', { name: 'To Riverside (1.0 mi, 3 min)' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next stop' })).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Open Riverside in the maps app' })).toHaveAttribute(
      'href',
      'geo:29.7,-95.4?q=29.7,-95.4(Riverside)',
    )
    const map = await findMap('Directions map for assignment 7')
    expect(map.querySelector('path.map-track')).not.toBeNull()
  })

  it('reads the next instruction aloud', async () => {
    const utterances: string[] = []
    vi.stubGlobal('speechSynthesis', { speak: (u: { text: string }) => utterances.push(u.text) })
    vi.stubGlobal(
      'SpeechSynthesisUtterance',
      class {
        text: string
        constructor(text: string) {
          this.text = text
        }
      },
    )
    vi.mocked(api.getDirections).mockResolvedValue(directions)
    const user = await open()
    await user.click(await screen.findByRole('button', { name: 'Read the next instruction aloud' }))
    expect(utterances).toEqual(['Head south on Oak Street'])
  })

  it('without directions, still lists the stops and links the next one', async () => {
    vi.mocked(api.getDirections).mockResolvedValue({
      ...directions,
      available: false,
      reason: 'Turn-by-turn directions need an OpenRouteService key (ISD_API_ORS_API_KEY).',
      legs: [],
      steps: [],
      coordinates: [],
    })
    await open()
    expect(await screen.findByText(/need an OpenRouteService key/)).toBeInTheDocument()
    expect(
      Array.from(document.querySelectorAll('.directions-waypoints li')).map((li) => li.textContent),
    ).toEqual(['Far', 'Near', 'Riverside'])
    expect(screen.getByRole('link', { name: 'Open Near in the maps app' })).toBeInTheDocument()
  })

  it('routes from the tablet position when asked', async () => {
    vi.mocked(api.getDirections).mockResolvedValue(directions)
    stubGeolocation({
      getCurrentPosition: (ok: PositionCallback) =>
        ok({ coords: { latitude: 29.8, longitude: -95.5 } } as GeolocationPosition),
    })
    const user = await open()
    await user.click(await screen.findByRole('button', { name: 'Route from my position' }))
    await waitFor(() =>
      expect(api.getDirections).toHaveBeenLastCalledWith(7, { lat: 29.8, lon: -95.5 }),
    )
  })

  it('shows why directions failed', async () => {
    vi.mocked(api.getDirections).mockRejectedValue(
      new ApiError(
        502,
        "Directions aren't available right now. Follow the stop order and try again.",
      ),
    )
    await open()
    expect(await screen.findByRole('alert')).toHaveTextContent('Follow the stop order')
  })

  it("shows a field trip's directions there and back", async () => {
    vi.mocked(api.getTripDirections).mockResolvedValue({
      ...directions,
      waypoints: [
        { label: 'North School', lat: 29.7, lon: -95.4 },
        { label: 'Science museum (bus loop)', lat: 29.75, lon: -95.36 },
        { label: 'North School', lat: 29.7, lon: -95.4 },
      ],
      legs: [
        { to_label: 'Science museum (bus loop)', distance_m: 8000, duration_s: 900 },
        { to_label: 'North School', distance_m: 8000, duration_s: 900 },
      ],
    })
    const user = userEvent.setup()
    render(<DirectionsPanel tripId={5} />)
    await user.click(screen.getByRole('button', { name: 'Directions' }))
    expect(await screen.findByText(/To Science museum \(bus loop\)/)).toBeInTheDocument()
    expect(api.getTripDirections).toHaveBeenCalledWith(5, undefined)
    expect(api.getDirections).not.toHaveBeenCalled()
    expect(await findMap('Directions map for field trip 5')).toBeInTheDocument()
  })
})
