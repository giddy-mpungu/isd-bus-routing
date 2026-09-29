import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { RouteTemplate, School, Stop } from '../api/types'
import { RouteStopsEditor } from './RouteStopsEditor'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, setRouteStops: vi.fn() }
})

const school: School = { id: 1, name: 'Riverside', location_lat: 29.7, location_lon: -95.4 }
const stops: Stop[] = [
  { id: 5, label: 'Oak', location_lat: 29.71, location_lon: -95.41 },
  { id: 6, label: 'Elm', location_lat: 29.72, location_lon: -95.42 },
  { id: 7, label: 'Pine', location_lat: 29.73, location_lon: -95.43 },
]
const template: RouteTemplate = {
  id: 3,
  school_id: 1,
  direction: 'am',
  window_earliest: 420,
  window_latest: 480,
  duration_minutes: 40,
  buffer_minutes: 0,
  days_of_week: [0, 1, 2, 3, 4],
  active_from: null,
  active_until: null,
  is_active: true,
  required_qualifications: [],
  stops: [
    {
      position: 1,
      stop_id: 5,
      stop_label: 'Oak',
      location_lat: 29.71,
      location_lon: -95.41,
      minutes_from_start: 0,
    },
    {
      position: 2,
      stop_id: 6,
      stop_label: 'Elm',
      location_lat: 29.72,
      location_lon: -95.42,
      minutes_from_start: 9,
    },
  ],
}

function renderEditor() {
  const onSaved = vi.fn()
  render(
    <RouteStopsEditor
      template={template}
      stops={stops}
      school={school}
      onSaved={onSaved}
      onClose={vi.fn()}
    />,
  )
  return onSaved
}

function order() {
  return Array.from(document.querySelectorAll('.route-stop-label')).map((el) => el.textContent)
}

describe('RouteStopsEditor', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('shows the stops in order with their planned minutes and the route on a map', async () => {
    renderEditor()
    expect(order()).toEqual(['Oak', 'Elm'])
    expect(
      screen.getByLabelText('Minutes from start', { selector: '#route-3-minutes-6' }),
    ).toHaveValue(9)
    const map = await screen.findByRole('region', { name: 'Route map for template 3' })
    expect(within(map).getByTitle('1. Oak')).toBeInTheDocument()
    expect(within(map).getByTitle('2. Elm')).toBeInTheDocument()
    expect(within(map).getByTitle('Riverside')).toBeInTheDocument()
    expect(map.querySelector('path.map-track')).not.toBeNull()
  })

  it('reorders, removes and adds stops, then saves the list in order', async () => {
    vi.mocked(api.setRouteStops).mockResolvedValue([])
    const onSaved = renderEditor()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Move Elm earlier' }))
    expect(order()).toEqual(['Elm', 'Oak'])
    await user.click(screen.getByRole('button', { name: 'Remove Oak' }))
    await user.selectOptions(screen.getByLabelText('Add a stop'), '7')
    await user.click(screen.getByRole('button', { name: 'Add to route' }))
    expect(order()).toEqual(['Elm', 'Pine'])
    // Oak is back on offer once removed; Elm and Pine aren't.
    expect(
      Array.from((screen.getByLabelText('Add a stop') as HTMLSelectElement).options).map(
        (o) => o.textContent,
      ),
    ).toEqual(['Select a stop', 'Oak'])

    await user.type(
      screen.getByLabelText('Minutes from start', { selector: '#route-3-minutes-7' }),
      '15',
    )
    await user.click(screen.getByRole('button', { name: 'Save stops' }))

    await waitFor(() =>
      expect(api.setRouteStops).toHaveBeenCalledWith(3, [
        { stop_id: 6, minutes_from_start: 9 },
        { stop_id: 7, minutes_from_start: 15 },
      ]),
    )
    expect(onSaved).toHaveBeenCalled()
  })

  it('sends an empty planned time as null', async () => {
    vi.mocked(api.setRouteStops).mockResolvedValue([])
    renderEditor()
    const user = userEvent.setup()
    await user.clear(
      screen.getByLabelText('Minutes from start', { selector: '#route-3-minutes-6' }),
    )
    await user.click(screen.getByRole('button', { name: 'Save stops' }))
    await waitFor(() =>
      expect(api.setRouteStops).toHaveBeenCalledWith(3, [
        { stop_id: 5, minutes_from_start: 0 },
        { stop_id: 6, minutes_from_start: null },
      ]),
    )
  })

  it('shows why the server refused the list', async () => {
    vi.mocked(api.setRouteStops).mockRejectedValue(
      new ApiError(400, "Planned minutes from start can't go backwards along the route"),
    )
    const onSaved = renderEditor()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Save stops' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("can't go backwards")
    expect(onSaved).not.toHaveBeenCalled()
  })
})
