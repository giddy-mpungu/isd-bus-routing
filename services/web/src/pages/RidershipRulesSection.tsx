import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { RidershipRules } from '../api/types'

// Spec section 4.4: the district sets when families must report ridership
// changes by. Staff can still record a change after the cutoff.
const TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
]

function toTime(minute: number | null): string {
  if (minute == null) return ''
  return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
}

function toMinute(time: string): number | null {
  if (!time) return null
  const [h, m] = time.split(':').map(Number)
  return h * 60 + m
}

export function RidershipRulesSection({ canEdit }: { canEdit: boolean }) {
  const [saved, setSaved] = useState<RidershipRules | null>(null)
  const [timezone, setTimezone] = useState('')
  const [amCutoff, setAmCutoff] = useState('')
  const [pmCutoff, setPmCutoff] = useState('')
  const [routeLock, setRouteLock] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const rules = await api.getRidershipRules()
      setSaved(rules)
      setTimezone(rules.timezone)
      setAmCutoff(toTime(rules.am_cutoff_minute))
      setPmCutoff(toTime(rules.pm_cutoff_minute))
      setRouteLock(rules.route_lock_minutes != null ? String(rules.route_lock_minutes) : '')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load ridership rules.')
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
      const updated = await api.updateRidershipRules({
        timezone,
        am_cutoff_minute: toMinute(amCutoff),
        pm_cutoff_minute: toMinute(pmCutoff),
        route_lock_minutes: routeLock.trim() === '' ? null : Number(routeLock),
      })
      setSaved(updated)
      setMessage('Ridership rules saved.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save ridership rules.')
    } finally {
      setIsSaving(false)
    }
  }

  const zones = TIMEZONES.includes(timezone) || !timezone ? TIMEZONES : [timezone, ...TIMEZONES]

  return (
    <section className="ridership-rules-section">
      <h2>Ridership reporting</h2>
      <p>
        When families must tell you about a change to that day&apos;s ride. After the cutoff the
        family app stops accepting changes for that ride and asks them to call the office; staff can
        still record one. Leave a cutoff blank for none. Past days can never be changed by families.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && <p className="status">{message}</p>}
      {saved && (
        <form onSubmit={(event) => void handleSubmit(event)}>
          <label htmlFor="ridership-timezone">District time zone</label>
          <select
            id="ridership-timezone"
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
            disabled={!canEdit}
          >
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {zone.replace('_', ' ')}
              </option>
            ))}
          </select>
          <label htmlFor="ridership-am-cutoff">Morning ride changes close at</label>
          <input
            id="ridership-am-cutoff"
            type="time"
            value={amCutoff}
            onChange={(event) => setAmCutoff(event.target.value)}
            disabled={!canEdit}
          />
          <label htmlFor="ridership-pm-cutoff">Afternoon ride changes close at</label>
          <input
            id="ridership-pm-cutoff"
            type="time"
            value={pmCutoff}
            onChange={(event) => setPmCutoff(event.target.value)}
            disabled={!canEdit}
          />
          <label htmlFor="ridership-route-lock">
            Lock a route&apos;s stops this many minutes before it leaves
          </label>
          <input
            id="ridership-route-lock"
            type="number"
            min="1"
            max="240"
            value={routeLock}
            onChange={(event) => setRouteLock(event.target.value)}
            disabled={!canEdit}
          />
          <small>
            Empty for no lock. From then until the run is done, its stops can&apos;t be changed or
            re-planned, so the driver&apos;s list doesn&apos;t move under them.
          </small>
          {canEdit ? (
            <button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Save ridership rules'}
            </button>
          ) : (
            <p>Only a transportation administrator can change these.</p>
          )}
        </form>
      )}
    </section>
  )
}
