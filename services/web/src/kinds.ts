import type { BufferReason, RouteKind, TripKind } from './api/types'
import type { Phrase } from './i18n'

// Spec section 11's kinds of route. Phrases (src/i18n): the driver app
// shows them translated.
export const ROUTE_KINDS: RouteKind[] = ['regular', 'special_education', 'activity', 'shuttle']

export const ROUTE_KIND_LABELS: Record<RouteKind, Phrase> = {
  regular: 'Regular route',
  special_education: 'Special education route',
  activity: 'Activity route',
  shuttle: 'Shuttle',
}

// And of trip.
export const TRIP_KINDS: TripKind[] = ['field_trip', 'athletic', 'activity', 'other']

export const TRIP_KIND_LABELS: Record<TripKind, string> = {
  field_trip: 'Field trip',
  athletic: 'Athletic trip',
  activity: 'Activity trip',
  other: 'Other trip',
}

// Spec section 16's reasons for a route's buffer, in the spec's order.
export const BUFFER_REASONS: BufferReason[] = [
  'traffic',
  'loading',
  'wheelchair',
  'weather',
  'rail_crossings',
  'pre_trip',
  'fueling',
  'other',
]

export const BUFFER_REASON_LABELS: Record<BufferReason, string> = {
  traffic: 'Traffic',
  loading: 'Loading and unloading',
  wheelchair: 'Wheelchair securement',
  weather: 'Weather',
  rail_crossings: 'Railroad crossings',
  pre_trip: 'Pre-trip inspection',
  fueling: 'Fueling',
  other: 'Other',
}

// "Traffic 5, Railroad crossings 3"
export function describeBuffer(breakdown: Partial<Record<BufferReason, number>>): string {
  return BUFFER_REASONS.filter((r) => breakdown[r])
    .map((r) => `${BUFFER_REASON_LABELS[r]} ${breakdown[r]}`)
    .join(', ')
}
