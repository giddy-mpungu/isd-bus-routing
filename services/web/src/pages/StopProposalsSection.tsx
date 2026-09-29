import { useMemo, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { School, Stop, StopProposal, StopProposalsGenerated } from '../api/types'
import { Badge } from '../components/Badge'
import { LazyMapView } from '../components/LazyMapView'
import type { MapMarker } from '../components/mapTypes'

const KIND_LABELS: Record<StopProposal['kind'], string> = {
  new: 'New stop',
  existing: 'Existing stop',
  curb: 'Curb stop (specialized)',
}

/**
 * Spec section 3.1: proposed stops for a school's eligible students, from
 * their homes and the district's walk limits and spacing. Staff approve,
 * reject or relocate each one. Transportation admins only, since proposals
 * show where students live. Proposals aren't snapped to streets and can't
 * see traffic, crossings or sight lines: check each on the map.
 */
export function StopProposalsSection({
  schools,
  stops,
  onChanged,
}: {
  schools: School[]
  stops: Stop[]
  // Setup reloads stops and students after an approval.
  onChanged: () => Promise<void>
}) {
  const [schoolId, setSchoolId] = useState('')
  const [proposals, setProposals] = useState<StopProposal[]>([])
  const [summary, setSummary] = useState<StopProposalsGenerated | null>(null)
  const [movingId, setMovingId] = useState<number | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function pickSchool(value: string) {
    setSchoolId(value)
    setSummary(null)
    setMovingId(null)
    setError(null)
    setProposals([])
    if (value === '') return
    try {
      setProposals(await api.getStopProposals(Number(value)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load proposals.')
    }
  }

  async function generate() {
    setError(null)
    setIsGenerating(true)
    try {
      const result = await api.generateStopProposals(Number(schoolId))
      setSummary(result)
      setProposals(await api.getStopProposals(Number(schoolId)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to propose stops.')
    } finally {
      setIsGenerating(false)
    }
  }

  async function act(id: number, action: () => Promise<StopProposal>, reload: boolean) {
    setError(null)
    setBusyId(id)
    try {
      const updated = await action()
      setProposals((prev) => prev.map((p) => (p.id === id ? updated : p)))
      if (reload) await onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That change failed.')
    } finally {
      setBusyId(null)
    }
  }

  const pending = proposals.filter((p) => p.status === 'pending')
  const decided = proposals.filter((p) => p.status !== 'pending')
  const school = schools.find((s) => String(s.id) === schoolId)

  const markers = useMemo<MapMarker[]>(() => {
    const list: MapMarker[] = []
    if (school) {
      list.push({
        id: 'school',
        lat: school.location_lat,
        lon: school.location_lon,
        label: school.name,
        tone: 'school',
      })
    }
    const proposedStopIds = new Set(pending.map((p) => p.stop_id))
    for (const s of stops) {
      if (!proposedStopIds.has(s.id)) {
        list.push({
          id: `stop-${s.id}`,
          lat: s.location_lat,
          lon: s.location_lon,
          label: s.label,
          tone: 'stop',
        })
      }
    }
    for (const p of pending) {
      list.push({
        id: `proposal-${p.id}`,
        lat: p.location_lat,
        lon: p.location_lon,
        label: `${p.label} (${p.riders.length})`,
        tone: p.kind === 'existing' ? 'stop' : 'pick',
      })
    }
    return list
  }, [school, stops, pending])

  return (
    <section className="stop-proposals-section">
      <h2>Stop proposals</h2>
      <p className="status">
        Proposes stops for eligible students who have a home on file and no stop yet, within their
        walk limits. It can&apos;t see roads, traffic or crossings, so check each one on the map
        before approving.
      </p>
      <label htmlFor="proposals-school">School</label>
      <select
        id="proposals-school"
        value={schoolId}
        onChange={(event) => void pickSchool(event.target.value)}
      >
        <option value="">Select a school</option>
        {schools.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={schoolId === '' || isGenerating}
        onClick={() => void generate()}
      >
        {isGenerating ? 'Proposing…' : 'Propose stops'}
      </button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {summary && (
        <p className="status">
          {summary.proposals.length} proposal(s) for {summary.students_considered} student(s). Left
          out: {summary.already_have_stop} already have a stop, {summary.no_home} have no home on
          file, {summary.not_eligible} aren&apos;t eligible.
        </p>
      )}
      {schoolId !== '' && (
        <>
          {movingId !== null && (
            <p className="status">
              Click the map to move {pending.find((p) => p.id === movingId)?.label}.
            </p>
          )}
          <LazyMapView
            markers={markers}
            label="Stop proposals map"
            onPick={
              movingId === null
                ? undefined
                : (lat, lon) => {
                    const id = movingId
                    setMovingId(null)
                    void act(
                      id,
                      () => api.updateStopProposal(id, { location_lat: lat, location_lon: lon }),
                      false,
                    )
                  }
            }
          />
          {pending.length === 0 && decided.length === 0 && (
            <p className="status">No proposals for this school yet.</p>
          )}
          <ul className="stop-proposals-list">
            {pending.map((p) => (
              <li key={p.id}>
                <strong>{p.label}</strong> <Badge tone="info">{KIND_LABELS[p.kind]}</Badge>
                <ul>
                  {p.riders.map((r) => (
                    <li key={r.student_id}>
                      {r.full_name}
                      {r.walk_miles != null &&
                        ` — walks ${r.walk_miles.toFixed(2)} mi (limit ${r.walk_limit_miles} mi)`}
                    </li>
                  ))}
                </ul>
                {p.warnings.map((w) => (
                  <p key={w} className="stop-proposal-warning">
                    ⚠ {w}
                  </p>
                ))}
                <button
                  type="button"
                  disabled={busyId === p.id}
                  onClick={() => void act(p.id, () => api.approveStopProposal(p.id), true)}
                >
                  Approve
                </button>{' '}
                <button
                  type="button"
                  className="btn-danger"
                  disabled={busyId === p.id}
                  onClick={() => void act(p.id, () => api.rejectStopProposal(p.id), false)}
                >
                  Reject
                </button>{' '}
                {p.kind !== 'existing' && (
                  <button
                    type="button"
                    disabled={busyId === p.id}
                    aria-pressed={movingId === p.id}
                    onClick={() => setMovingId(movingId === p.id ? null : p.id)}
                  >
                    {movingId === p.id ? 'Cancel move' : 'Move on map'}
                  </button>
                )}
              </li>
            ))}
          </ul>
          {decided.length > 0 && (
            <details>
              <summary>Decided ({decided.length})</summary>
              <ul>
                {decided.map((p) => (
                  <li key={p.id}>
                    {p.label}: {p.status} ({p.riders.length} student(s))
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  )
}
