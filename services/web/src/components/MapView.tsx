import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { NO_TRACKS, type MapMarker, type MapTrack } from './mapTypes'

export type { MapMarker, MapTrack, MarkerTone } from './mapTypes'

// Map tiles come from OpenStreetMap unless the deployment points
// VITE_MAP_TILE_URL at another provider or a self-hosted tile server. The
// tile server sees which area a viewer looks at, so a district may want its
// own (docs/deployment.md, "Map tiles"). The image's Content-Security-Policy
// allows this host via scripts/csp.mjs, which has the same default.
const TILE_URL =
  import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION =
  import.meta.env.VITE_MAP_ATTRIBUTION ||
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

// Where an empty map starts: the continental US, zoomed out.
const DEFAULT_CENTER: L.LatLngTuple = [39.8, -98.6]
const DEFAULT_ZOOM = 4

function markerIcon(marker: MapMarker): L.DivIcon {
  // Built as DOM nodes with textContent, never as an HTML string: labels
  // are user-entered (bus labels, stop names).
  const root = document.createElement('div')
  root.className = `map-pin map-pin-${marker.tone}`
  const dot = document.createElement('span')
  dot.className = 'map-pin-dot'
  const text = document.createElement('span')
  text.className = 'map-pin-label'
  text.textContent = marker.label
  root.append(dot, text)
  // A 14px dot centred on the point; the label hangs off to its right.
  return L.divIcon({
    html: root,
    className: 'map-pin-wrapper',
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  })
}

/**
 * A Leaflet map of labelled points. Pass `onPick` to let the user click the
 * map to choose a location (the typed coordinates stay the accessible way
 * in). `maxZoom` caps how far in the view goes, e.g. for an approximate
 * position that shouldn't look exact.
 */
export function MapView({
  markers,
  tracks = NO_TRACKS,
  label,
  onPick,
  maxZoom = 18,
  height = 320,
}: {
  markers: MapMarker[]
  tracks?: MapTrack[]
  label: string
  onPick?: (lat: number, lon: number) => void
  maxZoom?: number
  height?: number
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)
  const onPickRef = useRef(onPick)
  // Refit only when the set of points changes, not on every position
  // update, so a dispatcher who has panned the map isn't yanked back.
  const fittedKeyRef = useRef<string | null>(null)

  useEffect(() => {
    onPickRef.current = onPick
  }, [onPick])

  useEffect(() => {
    if (containerRef.current === null) return
    const map = L.map(containerRef.current, { maxZoom }).setView(DEFAULT_CENTER, DEFAULT_ZOOM)
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom }).addTo(map)
    layerRef.current = L.layerGroup().addTo(map)
    map.on('click', (event: L.LeafletMouseEvent) => {
      const pick = onPickRef.current
      if (pick) {
        pick(Number(event.latlng.lat.toFixed(6)), Number(event.latlng.lng.toFixed(6)))
      }
    })
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      layerRef.current = null
      fittedKeyRef.current = null
    }
  }, [maxZoom])

  useEffect(() => {
    const map = mapRef.current
    const layer = layerRef.current
    if (map === null || layer === null) return
    layer.clearLayers()
    for (const track of tracks) {
      if (track.points.length > 1) {
        L.polyline(track.points, { className: 'map-track', weight: 4, opacity: 0.8 })
          .bindTooltip(track.label)
          .addTo(layer)
      }
    }
    for (const marker of markers) {
      L.marker([marker.lat, marker.lon], {
        icon: markerIcon(marker),
        title: marker.label,
        alt: marker.label,
        keyboard: false,
      }).addTo(layer)
    }
    const points: L.LatLngTuple[] = [
      ...markers.map((m) => [m.lat, m.lon] as L.LatLngTuple),
      ...tracks.flatMap((t) => t.points),
    ]
    const key = [...markers.map((m) => m.id), ...tracks.map((t) => `track:${t.id}`)]
      .sort()
      .join('|')
    if (points.length === 0 || key === fittedKeyRef.current) return
    fittedKeyRef.current = key
    if (points.length === 1) {
      map.setView(points[0], Math.min(15, maxZoom))
    } else {
      map.fitBounds(L.latLngBounds(points), {
        padding: [30, 30],
        maxZoom: Math.min(16, maxZoom),
      })
    }
  }, [markers, tracks, maxZoom])

  return (
    <div
      ref={containerRef}
      className={`map-view${onPick ? ' is-pickable' : ''}`}
      role="region"
      aria-label={label}
      style={{ height }}
    />
  )
}
