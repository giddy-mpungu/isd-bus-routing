import { useMemo, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { RouteStop, RouteTemplate, School, Stop } from '../api/types'
import { LazyMapView } from '../components/LazyMapView'
import type { MapMarker, MapTrack } from '../components/mapTypes'

interface Draft {
  stop_id: number
  minutes: string
}

/**
 * Spec sections 3 and 9: a recurring route's stops, in the order the bus
 * visits them, each with an optional planned time after the run starts.
 * The map draws the route in order: stops then school in the morning,
 * school then stops in the afternoon.
 */
export function RouteStopsEditor({
  template,
  stops,
  school,
  onSaved,
  onClose,
}: {
  template: RouteTemplate
  stops: Stop[]
  school: School | undefined
  onSaved: (stops: RouteStop[]) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState<Draft[]>(() =>
    (template.stops ?? []).map((s) => ({
      stop_id: s.stop_id,
      minutes: s.minutes_from_start == null ? '' : String(s.minutes_from_start),
    })),
  )
  const [toAdd, setToAdd] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  const stopsById = useMemo(() => new Map(stops.map((s) => [s.id, s])), [stops])
  const available = stops.filter((s) => !draft.some((d) => d.stop_id === s.id))

  function move(index: number, by: number) {
    setDraft((prev) => {
      const next = [...prev]
      const [item] = next.splice(index, 1)
      next.splice(index + by, 0, item)
      return next
    })
  }

  function setMinutes(index: number, minutes: string) {
    setDraft((prev) => prev.map((d, i) => (i === index ? { ...d, minutes } : d)))
  }

  async function save() {
    setError(null)
    setIsSaving(true)
    try {
      onSaved(
        await api.setRouteStops(
          template.id,
          draft.map((d) => ({
            stop_id: d.stop_id,
            minutes_from_start: d.minutes === '' ? null : Number(d.minutes),
          })),
        ),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save the stops.')
    } finally {
      setIsSaving(false)
    }
  }

  const { markers, tracks } = useMemo(() => {
    const ordered = draft
      .map((d) => stopsById.get(d.stop_id))
      .filter((s): s is Stop => s !== undefined)
    const stopMarkers: MapMarker[] = ordered.map((s, i) => ({
      id: `stop-${s.id}`,
      lat: s.location_lat,
      lon: s.location_lon,
      label: `${i + 1}. ${s.label}`,
      tone: 'stop',
    }))
    const schoolPoint: [number, number][] = school
      ? [[school.location_lat, school.location_lon]]
      : []
    const stopPoints: [number, number][] = ordered.map((s) => [s.location_lat, s.location_lon])
    const points =
      template.direction === 'am'
        ? [...stopPoints, ...schoolPoint]
        : [...schoolPoint, ...stopPoints]
    const schoolMarkers: MapMarker[] = school
      ? [
          {
            id: 'school',
            lat: school.location_lat,
            lon: school.location_lon,
            label: school.name,
            tone: 'school',
          },
        ]
      : []
    const line: MapTrack[] =
      points.length > 1 ? [{ id: `route-${template.id}`, label: 'Route order', points }] : []
    return { markers: [...schoolMarkers, ...stopMarkers], tracks: line }
  }, [draft, stopsById, school, template.direction, template.id])

  const id = `route-${template.id}`
  return (
    <div className="route-stops-editor">
      <h4>
        Stops in order ({template.direction === 'am' ? 'then to school' : 'after leaving school'})
      </h4>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {draft.length === 0 && <p className="status">No stops on this route yet.</p>}
      <ol>
        {draft.map((d, index) => {
          const stop = stopsById.get(d.stop_id)
          const label = stop?.label ?? `Stop #${d.stop_id}`
          return (
            <li key={d.stop_id}>
              <span className="route-stop-label">{label}</span>{' '}
              <label htmlFor={`${id}-minutes-${d.stop_id}`}>Minutes from start</label>
              <input
                id={`${id}-minutes-${d.stop_id}`}
                type="number"
                min="0"
                max={template.duration_minutes}
                value={d.minutes}
                placeholder="—"
                onChange={(event) => setMinutes(index, event.target.value)}
              />
              <button
                type="button"
                aria-label={`Move ${label} earlier`}
                disabled={index === 0}
                onClick={() => move(index, -1)}
              >
                ↑
              </button>
              <button
                type="button"
                aria-label={`Move ${label} later`}
                disabled={index === draft.length - 1}
                onClick={() => move(index, 1)}
              >
                ↓
              </button>
              <button
                type="button"
                aria-label={`Remove ${label}`}
                onClick={() => setDraft((prev) => prev.filter((_, i) => i !== index))}
              >
                ✕
              </button>
            </li>
          )
        })}
      </ol>
      <label htmlFor={`${id}-add`}>Add a stop</label>
      <select id={`${id}-add`} value={toAdd} onChange={(event) => setToAdd(event.target.value)}>
        <option value="">Select a stop</option>
        {available.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={toAdd === ''}
        onClick={() => {
          setDraft((prev) => [...prev, { stop_id: Number(toAdd), minutes: '' }])
          setToAdd('')
        }}
      >
        Add to route
      </button>
      <LazyMapView
        markers={markers}
        tracks={tracks}
        label={`Route map for template ${template.id}`}
        height={260}
      />
      <button type="button" onClick={() => void save()} disabled={isSaving}>
        {isSaving ? 'Saving…' : 'Save stops'}
      </button>
      <button type="button" onClick={onClose} disabled={isSaving}>
        Close
      </button>
    </div>
  )
}
