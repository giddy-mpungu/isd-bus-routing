import { useEffect, useMemo, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { ClosureKind, RoadClosure, School } from '../api/types'
import { Badge } from '../components/Badge'
import { LazyMapView } from '../components/LazyMapView'
import type { MapMarker } from '../components/mapTypes'

const KINDS: { value: ClosureKind; label: string }[] = [
  { value: 'road_closed', label: 'Road closed' },
  { value: 'collision', label: 'Collision' },
  { value: 'construction', label: 'Construction' },
  { value: 'flooding', label: 'Flooding' },
  { value: 'police_activity', label: 'Police activity' },
  { value: 'severe_congestion', label: 'Severe congestion' },
  { value: 'other', label: 'Other' },
]
const KIND_LABELS = Object.fromEntries(KINDS.map((k) => [k.value, k.label])) as Record<
  ClosureKind,
  string
>

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// "HH:MM" today, local time, as an ISO timestamp.
function todayAt(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  const d = new Date()
  d.setHours(h, m, 0, 0)
  return d.toISOString()
}

/**
 * Spec section 10: a dispatcher records a crash, a flooded road or a police
 * scene by clicking the map. Drivers' directions route around closures in
 * force, and the runs that pass near one are listed here and in the alerts.
 */
export function RoadClosuresSection({ schools }: { schools: School[] }) {
  const [closures, setClosures] = useState<RoadClosure[]>([])
  const [error, setError] = useState<string | null>(null)
  const [kind, setKind] = useState<ClosureKind>('collision')
  const [note, setNote] = useState('')
  const [radius, setRadius] = useState('150')
  const [until, setUntil] = useState('')
  const [spot, setSpot] = useState<[number, number] | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)

  async function reload() {
    setClosures(await api.getRoadClosures())
  }

  useEffect(() => {
    let current = true
    api.getRoadClosures().then(
      (rows) => {
        if (current) setClosures(rows)
      },
      (err: unknown) => {
        if (current) setError(err instanceof ApiError ? err.message : 'Failed to load closures.')
      },
    )
    return () => {
      current = false
    }
  }, [])

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (spot === null) return
    setError(null)
    setIsSaving(true)
    try {
      await api.createRoadClosure({
        kind,
        note,
        location_lat: spot[0],
        location_lon: spot[1],
        radius_m: Number(radius),
        ends_at: until === '' ? null : todayAt(until),
      })
      setNote('')
      setUntil('')
      setSpot(null)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to record the closure.')
    } finally {
      setIsSaving(false)
    }
  }

  async function clear(closure: RoadClosure) {
    setError(null)
    setBusyId(closure.id)
    try {
      await api.clearRoadClosure(closure.id)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to clear the closure.')
    } finally {
      setBusyId(null)
    }
  }

  const markers = useMemo<MapMarker[]>(
    () => [
      ...schools.map((s) => ({
        id: `school-${s.id}`,
        lat: s.location_lat,
        lon: s.location_lon,
        label: s.name,
        tone: 'school' as const,
      })),
      ...closures.map((c) => ({
        id: `closure-${c.id}`,
        lat: c.location_lat,
        lon: c.location_lon,
        label: KIND_LABELS[c.kind],
        tone: 'closure' as const,
      })),
      ...(spot
        ? [{ id: 'new', lat: spot[0], lon: spot[1], label: 'New closure', tone: 'pick' as const }]
        : []),
    ],
    [schools, closures, spot],
  )

  return (
    <section className="road-closures-section">
      <h2>Road closures</h2>
      <p className="status">
        Drivers&apos; directions route around closures in force, keeping to roads fit for a bus.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {closures.length === 0 && <p className="status">No closures in force or coming up.</p>}
      <ul className="road-closures-list">
        {closures.map((c) => (
          <li key={c.id}>
            <Badge tone={c.active ? 'danger' : 'neutral'}>
              {c.active ? 'In force' : 'Coming up'}
            </Badge>{' '}
            <strong>{KIND_LABELS[c.kind]}</strong>: {c.note} ({c.radius_m} m
            {c.ends_at ? `, until ${clock(c.ends_at)}` : ', until cleared'})
            {c.affected_runs.length > 0 && (
              <ul>
                {c.affected_runs.map((r) => (
                  <li key={r.assignment_id}>
                    {r.stop_inside
                      ? `⚠ ${r.description}: the ${r.stop_inside} stop is inside it`
                      : r.description}
                  </li>
                ))}
              </ul>
            )}{' '}
            <button type="button" disabled={busyId === c.id} onClick={() => void clear(c)}>
              Road is open again
            </button>
          </li>
        ))}
      </ul>
      <h3>Record a closure</h3>
      <p className="status">Click the map where it is.</p>
      <LazyMapView
        markers={markers}
        label="Road closures map"
        onPick={(lat, lon) => setSpot([lat, lon])}
        height={280}
      />
      <form onSubmit={(event) => void handleCreate(event)}>
        <label htmlFor="closure-kind">What</label>
        <select
          id="closure-kind"
          value={kind}
          onChange={(event) => setKind(event.target.value as ClosureKind)}
        >
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        <label htmlFor="closure-note">Details</label>
        <input
          id="closure-note"
          value={note}
          maxLength={500}
          onChange={(event) => setNote(event.target.value)}
          required
        />
        <label htmlFor="closure-radius">Area to avoid (metres around the spot)</label>
        <input
          id="closure-radius"
          type="number"
          min="25"
          max="3000"
          value={radius}
          onChange={(event) => setRadius(event.target.value)}
          required
        />
        <label htmlFor="closure-until">Until (today; empty means until cleared)</label>
        <input
          id="closure-until"
          type="time"
          value={until}
          onChange={(event) => setUntil(event.target.value)}
        />
        <button type="submit" disabled={isSaving || spot === null}>
          {spot === null ? 'Click the map first' : isSaving ? 'Saving…' : 'Record closure'}
        </button>
      </form>
    </section>
  )
}
