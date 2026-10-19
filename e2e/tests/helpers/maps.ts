import { test } from '@playwright/test'

/**
 * The stand-in map services (fakes/maps.mjs: the Census geocoder and
 * OpenRouteService), when the harness runs them (--maps).
 */
export const MAPS_URL = process.env.E2E_MAPS_URL ?? ''

export function needsMaps() {
  test.skip(!MAPS_URL, 'No stand-in map services in this run (harness --maps)')
}

export interface MapRequest {
  service: 'census' | 'ors'
  path?: string
  query?: Record<string, string>
  body?: {
    coordinates?: number[][]
    options?: {
      avoid_polygons?: { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown[] }
      profile_params?: { restrictions?: Record<string, number> }
    }
  }
}

/** Everything the system has asked the map services, oldest first. */
export async function mapRequests(): Promise<MapRequest[]> {
  return (await (await fetch(`${MAPS_URL}/requests`)).json()) as MapRequest[]
}
