import { screen, waitFor } from '@testing-library/react'
import { expect } from 'vitest'

/**
 * Finds a lazily loaded map (components/LazyMapView.tsx) once Leaflet has
 * set it up, not merely once its container is in the DOM.
 *
 * MapView renders its region first and builds the Leaflet map, its pins,
 * its lines and its click handler in effects that run a moment later. A
 * plain findByRole can resolve in between. Whether the test then sees an
 * empty map depends on timing that shifts under a full-suite load, so pin
 * checks or map clicks straight after it fail intermittently. Leaflet adds
 * its map pane in the same effect pass that draws the points, so once the
 * pane is there, so is everything else. (Not the `leaflet-container`
 * class: React rewrites the container's className whenever `is-pickable`
 * toggles, which drops Leaflet's classes.)
 */
export function findMap(name: string): Promise<HTMLElement> {
  return waitFor(() => {
    const map = screen.getByRole('region', { name })
    expect(map.querySelector('.leaflet-map-pane')).not.toBeNull()
    return map
  })
}
