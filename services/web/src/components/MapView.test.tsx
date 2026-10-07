import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MapView, type MapMarker } from './MapView'

const bus: MapMarker = { id: 'bus-1', lat: 29.71, lon: -95.41, label: 'Bus 101', tone: 'bus' }
const school: MapMarker = {
  id: 'school-1',
  lat: 29.7,
  lon: -95.4,
  label: 'Riverside Elementary',
  tone: 'school',
}

describe('MapView', () => {
  it('draws a labelled pin per point, with OpenStreetMap attribution', () => {
    render(<MapView markers={[bus, school]} label="Fleet map" />)
    const map = screen.getByRole('region', { name: 'Fleet map' })
    expect(within(map).getByTitle('Bus 101')).toBeInTheDocument()
    expect(within(map).getByTitle('Riverside Elementary')).toBeInTheDocument()
    expect(map.querySelector('.map-pin-school')).not.toBeNull()
    expect(map).toHaveTextContent('OpenStreetMap')
  })

  it('shows labels as text, never as HTML', () => {
    const label = '<img src="x" onerror="alert(1)">'
    render(<MapView markers={[{ ...bus, label }]} label="Fleet map" />)
    const map = screen.getByRole('region', { name: 'Fleet map' })
    expect(map.querySelector('.map-pin-label')?.textContent).toBe(label)
    expect(map.querySelector('.map-pin img')).toBeNull()
  })

  it('updates the pins when the points change', () => {
    const { rerender } = render(<MapView markers={[bus]} label="Fleet map" />)
    rerender(<MapView markers={[{ ...bus, label: 'Bus 102' }, school]} label="Fleet map" />)
    const map = screen.getByRole('region', { name: 'Fleet map' })
    expect(within(map).queryByTitle('Bus 101')).not.toBeInTheDocument()
    expect(within(map).getByTitle('Bus 102')).toBeInTheDocument()
    expect(map.querySelectorAll('.map-pin')).toHaveLength(2)
  })

  it('reports a clicked location when picking is on', () => {
    const onPick = vi.fn()
    render(<MapView markers={[]} label="Stops map" onPick={onPick} />)
    const map = screen.getByRole('region', { name: 'Stops map' })
    expect(map).toHaveClass('is-pickable')

    fireEvent.click(map, { clientX: 5, clientY: 5 })

    expect(onPick).toHaveBeenCalledTimes(1)
    const [lat, lon] = onPick.mock.calls[0]
    expect(Number.isFinite(lat) && Number.isFinite(lon)).toBe(true)
  })

  it('is not pickable without onPick', () => {
    render(<MapView markers={[bus]} label="Fleet map" />)
    expect(screen.getByRole('region', { name: 'Fleet map' })).not.toHaveClass('is-pickable')
  })

  it('picks the centre of the map without a mouse', () => {
    const onPick = vi.fn()
    render(<MapView markers={[bus, school]} label="Fleet map" onPick={onPick} />)
    fireEvent.click(screen.getByRole('button', { name: 'Place it at the centre of the map' }))
    expect(onPick).toHaveBeenCalledTimes(1)
    const [lat, lon] = onPick.mock.calls[0]
    expect(Number.isFinite(lat) && Number.isFinite(lon)).toBe(true)
  })

  it('offers the centre button only when picking is on', () => {
    render(<MapView markers={[bus]} label="Fleet map" />)
    expect(screen.queryByRole('button', { name: /centre of the map/ })).not.toBeInTheDocument()
  })

  it("keeps Leaflet's own classes when picking turns on and off", () => {
    // leaflet-container carries Leaflet's overflow: hidden, which keeps
    // the tiles inside the map's box.
    const { rerender } = render(<MapView markers={[bus]} label="Fleet map" />)
    const map = screen.getByRole('region', { name: 'Fleet map' })
    expect(map).toHaveClass('map-view', 'leaflet-container')

    rerender(<MapView markers={[bus]} label="Fleet map" onPick={vi.fn()} />)
    expect(map).toHaveClass('map-view', 'is-pickable', 'leaflet-container')

    rerender(<MapView markers={[bus]} label="Fleet map" />)
    expect(map).not.toHaveClass('is-pickable')
    expect(map).toHaveClass('map-view', 'leaflet-container')
  })

  it('draws a track as a line', () => {
    render(
      <MapView
        markers={[bus]}
        tracks={[
          {
            id: '1',
            label: 'Bus 101 today',
            points: [
              [29.7, -95.4],
              [29.71, -95.41],
              [29.72, -95.42],
            ],
          },
        ]}
        label="Fleet map"
      />,
    )
    const map = screen.getByRole('region', { name: 'Fleet map' })
    expect(map.querySelectorAll('path.map-track')).toHaveLength(1)
  })

  it('skips a track with a single point', () => {
    render(
      <MapView
        markers={[bus]}
        tracks={[{ id: '1', label: 'x', points: [[29.7, -95.4]] }]}
        label="Fleet map"
      />,
    )
    expect(
      screen.getByRole('region', { name: 'Fleet map' }).querySelectorAll('path.map-track'),
    ).toHaveLength(0)
  })
})
