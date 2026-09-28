// Spec section 9: "Selected functions should be disabled or restricted while
// the vehicle is in motion." The driver app decides "moving" from the
// tablet's own GPS: the reported speed, or, when the device doesn't report
// one, the distance between two fixes over the time between them.

// About 5 mph: above this the bus is moving and typing locks.
export const MOVING_MPS = 2.2
// About 2 mph: it has to slow below this before the lock lifts, so it
// doesn't flicker on and off at a crawl (hysteresis).
export const STOPPED_MPS = 0.9

export interface Fix {
  lat: number
  lon: number
  // Milliseconds since the epoch.
  time: number
  // Metres per second, as the device reports it; null when it doesn't.
  speed: number | null
}

const EARTH_RADIUS_M = 6_371_000

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180
}

export function distanceMetres(a: Fix, b: Fix): number {
  const dLat = toRadians(b.lat - a.lat)
  const dLon = toRadians(b.lon - a.lon)
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRadians(a.lat)) * Math.cos(toRadians(b.lat)) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h))
}

/** Speed at `next` in m/s, or null when it can't be told. */
export function speedAt(previous: Fix | null, next: Fix): number | null {
  if (next.speed !== null && Number.isFinite(next.speed) && next.speed >= 0) {
    return next.speed
  }
  if (previous === null) return null
  const seconds = (next.time - previous.time) / 1000
  // Fixes too close together give a noisy speed.
  if (seconds < 2) return null
  return distanceMetres(previous, next) / seconds
}

/** Whether the bus counts as moving now, given what it was before. */
export function nextMoving(wasMoving: boolean, speed: number | null): boolean {
  if (speed === null) return wasMoving
  return wasMoving ? speed >= STOPPED_MPS : speed >= MOVING_MPS
}
