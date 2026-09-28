// Map data shapes, kept apart from MapView so pages can use them without
// pulling Leaflet into the main bundle (MapView loads lazily).

export type MarkerTone = 'bus' | 'school' | 'stop' | 'pick' | 'approx'

// A line through points in order, e.g. a bus's GPS track for the day.
export interface MapTrack {
  id: string
  label: string
  points: [number, number][]
}

// Shared, so a caller with no tracks doesn't redraw the map every render.
export const NO_TRACKS: MapTrack[] = []

export interface MapMarker {
  id: string
  lat: number
  lon: number
  label: string
  tone: MarkerTone
}
