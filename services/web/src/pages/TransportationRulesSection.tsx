import { useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { GradeBand, TransportationRules } from '../api/types'

const BANDS: GradeBand[] = ['prek', 'elementary', 'middle', 'high', 'specialized']

/**
 * Spec section 3.1: who is bus-eligible, and walk and ride limits by grade
 * band. Admins edit; dispatchers can read. Route building uses the walk
 * and ride limits; eligibility uses the distance now.
 */
export function TransportationRulesSection({ canEdit }: { canEdit: boolean }) {
  const [rules, setRules] = useState<TransportationRules | null>(null)
  const [eligibility, setEligibility] = useState('')
  const [walk, setWalk] = useState<Record<string, string>>({})
  const [ride, setRide] = useState<Record<string, string>>({})
  const [spacing, setSpacing] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  function show(r: TransportationRules) {
    setRules(r)
    setEligibility(String(r.eligibility_miles))
    setWalk(Object.fromEntries(BANDS.map((b) => [b, String(r.walk_miles[b])])))
    setRide(Object.fromEntries(BANDS.map((b) => [b, String(r.ride_minutes[b])])))
    setSpacing(String(r.min_stop_spacing_miles))
  }

  useEffect(() => {
    let current = true
    api.getTransportationRules().then(
      (r) => {
        if (current) show(r)
      },
      (err: unknown) => {
        if (current) {
          setError(err instanceof ApiError ? err.message : 'Failed to load the rules.')
        }
      },
    )
    return () => {
      current = false
    }
  }, [])

  async function handleSave(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSaved(false)
    setIsSaving(true)
    try {
      show(
        await api.updateTransportationRules({
          eligibility_miles: Number(eligibility),
          walk_miles: Object.fromEntries(BANDS.map((b) => [b, Number(walk[b])])) as Record<
            GradeBand,
            number
          >,
          ride_minutes: Object.fromEntries(BANDS.map((b) => [b, Number(ride[b])])) as Record<
            GradeBand,
            number
          >,
          min_stop_spacing_miles: Number(spacing),
        }),
      )
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save the rules.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <section className="transportation-rules-section">
      <h2>Eligibility, walk and ride limits</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {rules && (
        <form onSubmit={(event) => void handleSave(event)}>
          {rules.is_default && (
            <p className="status">Using the district defaults. Change any value and save.</p>
          )}
          <label htmlFor="rules-eligibility">Bus-eligible from (miles from school)</label>
          <input
            id="rules-eligibility"
            type="number"
            min="0"
            max="25"
            step="0.1"
            value={eligibility}
            disabled={!canEdit}
            onChange={(event) => setEligibility(event.target.value)}
            required
          />
          <label htmlFor="rules-spacing">Minimum spacing between stops (miles)</label>
          <input
            id="rules-spacing"
            type="number"
            min="0"
            max="2"
            step="0.05"
            value={spacing}
            disabled={!canEdit}
            onChange={(event) => setSpacing(event.target.value)}
            required
          />
          <table className="rules-table">
            <thead>
              <tr>
                <th>Grade band</th>
                <th>Longest walk to a stop (miles)</th>
                <th>Longest ride (minutes)</th>
              </tr>
            </thead>
            <tbody>
              {BANDS.map((band) => (
                <tr key={band}>
                  <th scope="row">{rules.band_labels[band]}</th>
                  <td>
                    <input
                      type="number"
                      min="0"
                      max="5"
                      step="0.05"
                      aria-label={`${rules.band_labels[band]} walk (miles)`}
                      value={walk[band] ?? ''}
                      disabled={!canEdit}
                      onChange={(event) => setWalk({ ...walk, [band]: event.target.value })}
                      required
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min="0"
                      max="240"
                      step="1"
                      aria-label={`${rules.band_labels[band]} ride (minutes)`}
                      value={ride[band] ?? ''}
                      disabled={!canEdit}
                      onChange={(event) => setRide({ ...ride, [band]: event.target.value })}
                      required
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {saved && <p className="status">Rules saved.</p>}
          {canEdit && (
            <button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Save limits'}
            </button>
          )}
        </form>
      )}
    </section>
  )
}
