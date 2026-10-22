import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { OptimizationSettings } from '../api/types'

// Spec section 2.2: administrators configure the relative weights of the
// soft objectives. Weights only rank schedules that already satisfy every
// hard constraint; they can never buy a rule violation.
const FIELDS: {
  key: 'crews_used_weight' | 'deadhead_minutes_weight' | 'arrival_buffer_weight'
  label: string
  help: string
}[] = [
  {
    key: 'crews_used_weight',
    label: 'Crews used',
    help: 'Prefer schedules that need fewer buses and drivers (a crew is one of each).',
  },
  {
    key: 'deadhead_minutes_weight',
    label: 'Deadhead travel',
    help: "Prefer less empty driving (per minute of travel): between runs, and from each bus's yard to its first run and back.",
  },
  {
    key: 'arrival_buffer_weight',
    label: 'Arrival buffer',
    help: 'Prefer finishing earlier, leaving more slack before each bell (per minute).',
  },
]

// Spec section 7: what the routing engine adds to a route's cost for each
// kind of turn, in seconds. They choose the route; times shown don't
// include them.
const TURN_COSTS: {
  key:
    | 'turn_right_seconds'
    | 'turn_sharp_right_seconds'
    | 'turn_left_seconds'
    | 'turn_sharp_left_seconds'
    | 'turn_main_road_left_seconds'
  label: string
}[] = [
  { key: 'turn_right_seconds', label: 'Right turn' },
  { key: 'turn_sharp_right_seconds', label: 'Sharp right turn' },
  { key: 'turn_left_seconds', label: 'Left turn' },
  { key: 'turn_sharp_left_seconds', label: 'Sharp left turn' },
  { key: 'turn_main_road_left_seconds', label: 'Left at a main road (on top of the left)' },
]

// Spec section 2.1: driver work-hour rules, entered by the district (this
// system asserts nothing about what any law requires). Empty means no rule.
const WORK_RULES: {
  key: 'max_duty_minutes' | 'break_after_minutes' | 'break_minutes' | 'min_rest_minutes'
  label: string
  unit: 'hours' | 'minutes'
  help: string
}[] = [
  {
    key: 'max_duty_minutes',
    label: 'Longest day on duty (hours)',
    unit: 'hours',
    help: "From a driver's first run to the end of their last.",
  },
  {
    key: 'break_after_minutes',
    label: 'Most work before a break (hours)',
    unit: 'hours',
    help: 'Driving between runs counts as work.',
  },
  {
    key: 'break_minutes',
    label: 'Shortest break (minutes)',
    unit: 'minutes',
    help: 'Set together with the work allowed before a break.',
  },
  {
    key: 'min_rest_minutes',
    label: 'Rest between days (hours)',
    unit: 'hours',
    help: "From the end of one day's work to the start of the next.",
  },
]

function shown(minutes: number | null, unit: 'hours' | 'minutes'): string {
  if (minutes === null) return ''
  return unit === 'hours' ? String(Math.round((minutes / 60) * 100) / 100) : String(minutes)
}

function entered(value: string | undefined, unit: 'hours' | 'minutes'): number | null {
  if (value === undefined || value.trim() === '') return null
  return unit === 'hours' ? Math.round(Number(value) * 60) : Math.round(Number(value))
}

export function OptimizationSettingsSection({ canEdit }: { canEdit: boolean }) {
  const [saved, setSaved] = useState<OptimizationSettings | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const settings = await api.getOptimizationSettings()
      setSaved(settings)
      setValues({
        crews_used_weight: String(settings.crews_used_weight),
        deadhead_minutes_weight: String(settings.deadhead_minutes_weight),
        arrival_buffer_weight: String(settings.arrival_buffer_weight),
        minimum_buffer_minutes: String(settings.minimum_buffer_minutes),
        ride_time_weight: String(settings.ride_time_weight),
        walking_weight: String(settings.walking_weight),
        ...Object.fromEntries(TURN_COSTS.map((c) => [c.key, String(settings[c.key])])),
        ...Object.fromEntries(WORK_RULES.map((r) => [r.key, shown(settings[r.key], r.unit)])),
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load optimization settings.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setMessage(null)
    setIsSaving(true)
    try {
      const updated = await api.updateOptimizationSettings({
        crews_used_weight: Number(values.crews_used_weight),
        deadhead_minutes_weight: Number(values.deadhead_minutes_weight),
        arrival_buffer_weight: Number(values.arrival_buffer_weight),
        minimum_buffer_minutes: Number(values.minimum_buffer_minutes),
        ride_time_weight: Number(values.ride_time_weight),
        walking_weight: Number(values.walking_weight),
        ...(Object.fromEntries(TURN_COSTS.map((c) => [c.key, Number(values[c.key])])) as Record<
          (typeof TURN_COSTS)[number]['key'],
          number
        >),
        max_duty_minutes: entered(values.max_duty_minutes, 'hours'),
        break_after_minutes: entered(values.break_after_minutes, 'hours'),
        break_minutes: entered(values.break_minutes, 'minutes'),
        min_rest_minutes: entered(values.min_rest_minutes, 'hours'),
      })
      setSaved(updated)
      setMessage('Settings saved. They apply the next time a schedule is solved.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save optimization settings.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <section className="optimization-settings-section">
      <h2>Optimization weights</h2>
      <p>
        Relative importance of each goal when the solver chooses among schedules that already
        satisfy every hard rule. Larger means more important. Crews are counted in whole crews and
        the other two in minutes, so give “Crews used” a proportionally larger weight (for example
        100 against 1) if saving a crew should win over extra driving.
        {saved?.is_default && ' Nothing has been saved yet, so the defaults are in effect.'}
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && <p className="status">{message}</p>}
      {saved && (
        <form onSubmit={(event) => void handleSubmit(event)}>
          {FIELDS.map((field) => (
            <div key={field.key}>
              <label htmlFor={`opt-${field.key}`}>{field.label}</label>
              <input
                id={`opt-${field.key}`}
                type="number"
                min="0"
                max="1000"
                step="1"
                value={values[field.key] ?? ''}
                onChange={(event) =>
                  setValues((prev) => ({ ...prev, [field.key]: event.target.value }))
                }
                disabled={!canEdit}
                required
              />
              <small>{field.help}</small>
            </div>
          ))}
          <div>
            <label htmlFor="opt-minimum_buffer_minutes">
              Minimum buffer between runs (minutes)
            </label>
            <input
              id="opt-minimum_buffer_minutes"
              type="number"
              min="0"
              max="120"
              step="1"
              value={values.minimum_buffer_minutes ?? ''}
              onChange={(event) =>
                setValues((prev) => ({ ...prev, minimum_buffer_minutes: event.target.value }))
              }
              disabled={!canEdit}
              required
            />
            <small>
              A hard rule, not a weight: every bus keeps at least this many spare minutes between
              one run and the next, after driving between them. A day that can&apos;t meet it is
              reported as unschedulable instead of being built too tight. 0 turns it off.
            </small>
          </div>
          <div>
            <label htmlFor="opt-ride_time_weight">Student ride time (route planning)</label>
            <input
              id="opt-ride_time_weight"
              type="number"
              min="0"
              max="10"
              step="1"
              value={values.ride_time_weight ?? ''}
              onChange={(event) =>
                setValues((prev) => ({ ...prev, ride_time_weight: event.target.value }))
              }
              disabled={!canEdit}
              required
            />
            <small>
              When &quot;Plan order and times&quot; orders a route&apos;s stops: 0 plans the fastest
              route; 1 counts each student&apos;s minute on the bus like a minute of the bus&apos;s
              own time, so stops with more children come closer to school.
            </small>
          </div>
          <div>
            <label htmlFor="opt-walking_weight">Shorter walks (proposing stops)</label>
            <input
              id="opt-walking_weight"
              type="number"
              min="0"
              max="10"
              step="1"
              value={values.walking_weight ?? ''}
              onChange={(event) =>
                setValues((prev) => ({ ...prev, walking_weight: event.target.value }))
              }
              disabled={!canEdit}
              required
            />
            <small>
              When stops are proposed: 0 lets children walk up to their grade&apos;s limit, for the
              fewest stops; each step takes 5% off every limit, down to half at 10, for shorter
              walks and more stops. Each stop goes where its children&apos;s walks add up to least.
            </small>
          </div>
          <fieldset className="work-rules">
            <legend>Turn costs (routing engine, seconds)</legend>
            <p>
              What each kind of turn adds when the routing engine chooses a bus&apos;s route: higher
              numbers mean more of a detour to avoid it. U-turns are used only where there&apos;s no
              other way, and never at a stop.
            </p>
            {TURN_COSTS.map((cost) => (
              <div key={cost.key}>
                <label htmlFor={`opt-${cost.key}`}>{cost.label}</label>
                <input
                  id={`opt-${cost.key}`}
                  type="number"
                  min="0"
                  max="600"
                  step="1"
                  value={values[cost.key] ?? ''}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [cost.key]: event.target.value }))
                  }
                  disabled={!canEdit}
                  required
                />
              </div>
            ))}
          </fieldset>
          <fieldset className="work-rules">
            <legend>Driver work hours</legend>
            <p>
              Rules the schedule must keep, from your district&apos;s policy or state law. Leave a
              box empty for no rule. They also apply when a run is moved by hand and when a driver
              is given a field trip.
            </p>
            {WORK_RULES.map((rule) => (
              <div key={rule.key}>
                <label htmlFor={`opt-${rule.key}`}>{rule.label}</label>
                <input
                  id={`opt-${rule.key}`}
                  type="number"
                  min={rule.unit === 'hours' ? '0.5' : '5'}
                  max={rule.unit === 'hours' ? '24' : '240'}
                  step={rule.unit === 'hours' ? '0.25' : '5'}
                  value={values[rule.key] ?? ''}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [rule.key]: event.target.value }))
                  }
                  disabled={!canEdit}
                />
                <small>{rule.help}</small>
              </div>
            ))}
          </fieldset>
          {canEdit ? (
            <button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Save settings'}
            </button>
          ) : (
            <p>Only a transportation administrator can change these.</p>
          )}
        </form>
      )}
    </section>
  )
}
