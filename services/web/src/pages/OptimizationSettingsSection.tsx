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
    help: 'Prefer schedules that need fewer buses and drivers.',
  },
  {
    key: 'deadhead_minutes_weight',
    label: 'Deadhead travel',
    help: 'Prefer less empty driving between schools (per minute of travel).',
  },
  {
    key: 'arrival_buffer_weight',
    label: 'Arrival buffer',
    help: 'Prefer finishing earlier, leaving more slack before each bell (per minute).',
  },
]

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
