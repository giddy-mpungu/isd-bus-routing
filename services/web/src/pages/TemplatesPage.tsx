import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  CrewTemplate,
  Driver,
  Qualification,
  RideDirection,
  RouteTemplate,
  School,
  Vehicle,
} from '../api/types'

// Python weekday numbers, matching the backend: Monday=0 .. Sunday=6.
const WEEKDAYS = [
  { value: 0, label: 'Mon' },
  { value: 1, label: 'Tue' },
  { value: 2, label: 'Wed' },
  { value: 3, label: 'Thu' },
  { value: 4, label: 'Fri' },
  { value: 5, label: 'Sat' },
  { value: 6, label: 'Sun' },
]

function formatMinuteOfDay(minute: number): string {
  const hours = Math.floor(minute / 60)
  const mins = minute % 60
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`
}

function formatDays(days: number[]): string {
  return WEEKDAYS.filter((d) => days.includes(d.value))
    .map((d) => d.label)
    .join(', ')
}

function formatRange(from: string | null, until: string | null): string {
  if (!from && !until) {
    return 'always'
  }
  return `${from ?? '…'} → ${until ?? '…'}`
}

function DayPicker({
  idPrefix,
  selected,
  onToggle,
}: {
  idPrefix: string
  selected: Set<number>
  onToggle: (day: number) => void
}) {
  return (
    <fieldset>
      <legend>Runs on</legend>
      {WEEKDAYS.map((d) => (
        <label key={d.value} htmlFor={`${idPrefix}-day-${d.value}`}>
          <input
            id={`${idPrefix}-day-${d.value}`}
            type="checkbox"
            checked={selected.has(d.value)}
            onChange={() => onToggle(d.value)}
          />
          {d.label}
        </label>
      ))}
    </fieldset>
  )
}

function toggled(set: Set<number>, day: number): Set<number> {
  const next = new Set(set)
  if (next.has(day)) {
    next.delete(day)
  } else {
    next.add(day)
  }
  return next
}

export function TemplatesPage() {
  const [routeTemplates, setRouteTemplates] = useState<RouteTemplate[]>([])
  const [crewTemplates, setCrewTemplates] = useState<CrewTemplate[]>([])
  const [schools, setSchools] = useState<School[]>([])
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [qualifications, setQualifications] = useState<Qualification[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const [rt, ct, s, d, v, q] = await Promise.all([
        api.getRouteTemplates(),
        api.getCrewTemplates(),
        api.getSchools(),
        api.getDrivers(),
        api.getVehicles(),
        api.getQualifications(),
      ])
      setRouteTemplates(rt)
      setCrewTemplates(ct)
      setSchools(s)
      setDrivers(d)
      setVehicles(v)
      setQualifications(q)
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : 'Failed to load templates.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const schoolsById = new Map(schools.map((s) => [s.id, s]))
  const driversById = new Map(drivers.map((d) => [d.id, d]))
  const vehiclesById = new Map(vehicles.map((v) => [v.id, v]))
  const vehicleQualifications = qualifications.filter(
    (q) => q.kind === 'vehicle_capability' && q.is_active,
  )
  const activeDrivers = drivers.filter((d) => d.is_active)
  const activeVehicles = vehicles.filter((v) => v.is_active)

  // --- Route template form ---
  const [rtSchoolId, setRtSchoolId] = useState('')
  const [rtDirection, setRtDirection] = useState<RideDirection>('am')
  const [rtEarliest, setRtEarliest] = useState('')
  const [rtLatest, setRtLatest] = useState('')
  const [rtDuration, setRtDuration] = useState('')
  const [rtBuffer, setRtBuffer] = useState('0')
  const [rtDays, setRtDays] = useState<Set<number>>(new Set([0, 1, 2, 3, 4]))
  const [rtFrom, setRtFrom] = useState('')
  const [rtUntil, setRtUntil] = useState('')
  const [rtQuals, setRtQuals] = useState<Set<string>>(new Set())
  const [rtError, setRtError] = useState<string | null>(null)
  const [isSavingRt, setIsSavingRt] = useState(false)

  async function handleCreateRouteTemplate(event: FormEvent) {
    event.preventDefault()
    setRtError(null)
    setIsSavingRt(true)
    try {
      await api.createRouteTemplate({
        school_id: Number(rtSchoolId),
        direction: rtDirection,
        window_earliest: Number(rtEarliest),
        window_latest: Number(rtLatest),
        duration_minutes: Number(rtDuration),
        buffer_minutes: Number(rtBuffer),
        days_of_week: [...rtDays].sort((a, b) => a - b),
        active_from: rtFrom || null,
        active_until: rtUntil || null,
        required_qualification_codes: [...rtQuals],
      })
      setRtEarliest('')
      setRtLatest('')
      setRtDuration('')
      setRtBuffer('0')
      setRtFrom('')
      setRtUntil('')
      setRtQuals(new Set())
      await load()
    } catch (err) {
      setRtError(err instanceof ApiError ? err.message : 'Failed to create route template.')
    } finally {
      setIsSavingRt(false)
    }
  }

  async function handleToggleRoute(template: RouteTemplate) {
    setLoadError(null)
    try {
      await api.setRouteTemplateActive(template.id, !template.is_active)
      await load()
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : 'Failed to update route template.')
    }
  }

  // --- Crew template form ---
  const [ctDriverId, setCtDriverId] = useState('')
  const [ctVehicleId, setCtVehicleId] = useState('')
  const [ctEarliest, setCtEarliest] = useState('0')
  const [ctLatest, setCtLatest] = useState('1439')
  const [ctDays, setCtDays] = useState<Set<number>>(new Set([0, 1, 2, 3, 4]))
  const [ctFrom, setCtFrom] = useState('')
  const [ctUntil, setCtUntil] = useState('')
  const [ctError, setCtError] = useState<string | null>(null)
  const [isSavingCt, setIsSavingCt] = useState(false)

  async function handleCreateCrewTemplate(event: FormEvent) {
    event.preventDefault()
    setCtError(null)
    setIsSavingCt(true)
    try {
      await api.createCrewTemplate({
        driver_id: Number(ctDriverId),
        vehicle_id: Number(ctVehicleId),
        available_window_earliest: Number(ctEarliest),
        available_window_latest: Number(ctLatest),
        days_of_week: [...ctDays].sort((a, b) => a - b),
        active_from: ctFrom || null,
        active_until: ctUntil || null,
      })
      setCtFrom('')
      setCtUntil('')
      await load()
    } catch (err) {
      setCtError(err instanceof ApiError ? err.message : 'Failed to create crew template.')
    } finally {
      setIsSavingCt(false)
    }
  }

  async function handleToggleCrew(template: CrewTemplate) {
    setLoadError(null)
    try {
      await api.setCrewTemplateActive(template.id, !template.is_active)
      await load()
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : 'Failed to update crew template.')
    }
  }

  return (
    <main className="templates-page">
      <h1>Recurring templates</h1>
      <p>
        Templates describe what normally repeats each week. They generate ordinary runs and crews
        for a chosen day (use “Generate from templates” on the Schedule page) — the solver still
        decides which crew serves which run, and a template never changes when you edit a single
        day.
      </p>
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}

      <section className="route-templates-section">
        <h2>Route templates</h2>
        {routeTemplates.length === 0 ? (
          <p>No route templates yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>School</th>
                <th>Leg</th>
                <th>Window</th>
                <th>Duration + buffer</th>
                <th>Days</th>
                <th>Active range</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {routeTemplates.map((t) => (
                <tr key={t.id}>
                  <td>{schoolsById.get(t.school_id)?.name ?? `School #${t.school_id}`}</td>
                  <td>{t.direction.toUpperCase()}</td>
                  <td>
                    {formatMinuteOfDay(t.window_earliest)}–{formatMinuteOfDay(t.window_latest)}
                  </td>
                  <td>
                    {t.duration_minutes} + {t.buffer_minutes} min
                  </td>
                  <td>{formatDays(t.days_of_week)}</td>
                  <td>{formatRange(t.active_from, t.active_until)}</td>
                  <td>{t.is_active ? 'Active' : 'Inactive'}</td>
                  <td>
                    <button type="button" onClick={() => void handleToggleRoute(t)}>
                      {t.is_active ? 'Deactivate' : 'Reactivate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h3>Add route template</h3>
        <form onSubmit={(event) => void handleCreateRouteTemplate(event)}>
          <label htmlFor="rt-school">School</label>
          <select
            id="rt-school"
            value={rtSchoolId}
            onChange={(event) => setRtSchoolId(event.target.value)}
            required
          >
            <option value="" disabled>
              Select a school
            </option>
            {schools.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <label htmlFor="rt-direction">Direction</label>
          <select
            id="rt-direction"
            value={rtDirection}
            onChange={(event) => setRtDirection(event.target.value as RideDirection)}
          >
            <option value="am">AM (to school)</option>
            <option value="pm">PM (from school)</option>
          </select>
          <label htmlFor="rt-earliest">Window start (minute of day)</label>
          <input
            id="rt-earliest"
            type="number"
            min="0"
            max="1439"
            value={rtEarliest}
            onChange={(event) => setRtEarliest(event.target.value)}
            required
          />
          <label htmlFor="rt-latest">Window end (minute of day)</label>
          <input
            id="rt-latest"
            type="number"
            min="0"
            max="1439"
            value={rtLatest}
            onChange={(event) => setRtLatest(event.target.value)}
            required
          />
          <label htmlFor="rt-duration">Duration (minutes)</label>
          <input
            id="rt-duration"
            type="number"
            min="1"
            value={rtDuration}
            onChange={(event) => setRtDuration(event.target.value)}
            required
          />
          <label htmlFor="rt-buffer">Buffer (minutes)</label>
          <input
            id="rt-buffer"
            type="number"
            min="0"
            value={rtBuffer}
            onChange={(event) => setRtBuffer(event.target.value)}
            required
          />
          <DayPicker
            idPrefix="rt"
            selected={rtDays}
            onToggle={(day) => setRtDays((prev) => toggled(prev, day))}
          />
          <label htmlFor="rt-from">Active from (optional)</label>
          <input
            id="rt-from"
            type="date"
            value={rtFrom}
            onChange={(event) => setRtFrom(event.target.value)}
          />
          <label htmlFor="rt-until">Active until (optional)</label>
          <input
            id="rt-until"
            type="date"
            value={rtUntil}
            onChange={(event) => setRtUntil(event.target.value)}
          />
          {vehicleQualifications.length > 0 && (
            <fieldset>
              <legend>Required vehicle capabilities</legend>
              {vehicleQualifications.map((q) => (
                <label key={q.id} htmlFor={`rt-qual-${q.code}`}>
                  <input
                    id={`rt-qual-${q.code}`}
                    type="checkbox"
                    checked={rtQuals.has(q.code)}
                    onChange={() =>
                      setRtQuals((prev) => {
                        const next = new Set(prev)
                        if (next.has(q.code)) {
                          next.delete(q.code)
                        } else {
                          next.add(q.code)
                        }
                        return next
                      })
                    }
                  />
                  {q.code}
                </label>
              ))}
            </fieldset>
          )}
          {rtError && (
            <p role="alert" className="error">
              {rtError}
            </p>
          )}
          <button type="submit" disabled={isSavingRt || rtDays.size === 0}>
            {isSavingRt ? 'Saving…' : 'Add route template'}
          </button>
        </form>
      </section>

      <section className="crew-templates-section">
        <h2>Crew templates</h2>
        {crewTemplates.length === 0 ? (
          <p>No crew templates yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Driver</th>
                <th>Vehicle</th>
                <th>Available</th>
                <th>Days</th>
                <th>Active range</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {crewTemplates.map((t) => (
                <tr key={t.id}>
                  <td>{driversById.get(t.driver_id)?.full_name ?? `Driver #${t.driver_id}`}</td>
                  <td>{vehiclesById.get(t.vehicle_id)?.label ?? `Vehicle #${t.vehicle_id}`}</td>
                  <td>
                    {formatMinuteOfDay(t.available_window_earliest)}–
                    {formatMinuteOfDay(t.available_window_latest)}
                  </td>
                  <td>{formatDays(t.days_of_week)}</td>
                  <td>{formatRange(t.active_from, t.active_until)}</td>
                  <td>{t.is_active ? 'Active' : 'Inactive'}</td>
                  <td>
                    <button type="button" onClick={() => void handleToggleCrew(t)}>
                      {t.is_active ? 'Deactivate' : 'Reactivate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h3>Add crew template</h3>
        <form onSubmit={(event) => void handleCreateCrewTemplate(event)}>
          <label htmlFor="ct-driver">Driver</label>
          <select
            id="ct-driver"
            value={ctDriverId}
            onChange={(event) => setCtDriverId(event.target.value)}
            required
          >
            <option value="" disabled>
              Select a driver
            </option>
            {activeDrivers.map((d) => (
              <option key={d.id} value={d.id}>
                {d.full_name}
              </option>
            ))}
          </select>
          <label htmlFor="ct-vehicle">Vehicle</label>
          <select
            id="ct-vehicle"
            value={ctVehicleId}
            onChange={(event) => setCtVehicleId(event.target.value)}
            required
          >
            <option value="" disabled>
              Select a vehicle
            </option>
            {activeVehicles.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
          <label htmlFor="ct-earliest">Available from (minute of day)</label>
          <input
            id="ct-earliest"
            type="number"
            min="0"
            max="1439"
            value={ctEarliest}
            onChange={(event) => setCtEarliest(event.target.value)}
            required
          />
          <label htmlFor="ct-latest">Available until (minute of day)</label>
          <input
            id="ct-latest"
            type="number"
            min="0"
            max="1439"
            value={ctLatest}
            onChange={(event) => setCtLatest(event.target.value)}
            required
          />
          <DayPicker
            idPrefix="ct"
            selected={ctDays}
            onToggle={(day) => setCtDays((prev) => toggled(prev, day))}
          />
          <label htmlFor="ct-from">Active from (optional)</label>
          <input
            id="ct-from"
            type="date"
            value={ctFrom}
            onChange={(event) => setCtFrom(event.target.value)}
          />
          <label htmlFor="ct-until">Active until (optional)</label>
          <input
            id="ct-until"
            type="date"
            value={ctUntil}
            onChange={(event) => setCtUntil(event.target.value)}
          />
          {ctError && (
            <p role="alert" className="error">
              {ctError}
            </p>
          )}
          <button type="submit" disabled={isSavingCt || ctDays.size === 0}>
            {isSavingCt ? 'Saving…' : 'Add crew template'}
          </button>
        </form>
      </section>
    </main>
  )
}
