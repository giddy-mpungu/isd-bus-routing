import { useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { ObservedRunDuration, RouteTemplate } from '../api/types'

/**
 * Spec section 20: "if a route consistently requires 48 minutes despite an
 * initial estimate of 40 minutes, future schedules should be capable of
 * adjusting toward the observed operational duration." How long this
 * route's completed runs actually took, and a way to plan with that.
 * Decision support: nothing changes until someone chooses to.
 */
export function ObservedRouteTime({
  template,
  onChanged,
}: {
  template: RouteTemplate
  onChanged: () => Promise<void>
}) {
  const [observed, setObserved] = useState<ObservedRunDuration | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  async function look() {
    setError(null)
    setIsBusy(true)
    try {
      setObserved(
        await api.getObservedRunDuration(template.school_id, template.direction, template.id),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load the observed time.')
    } finally {
      setIsBusy(false)
    }
  }

  async function adopt(minutes: number) {
    setError(null)
    setIsBusy(true)
    try {
      await api.setRouteTemplateDuration(template.id, minutes)
      await onChanged()
      setObserved(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to update the route.')
    } finally {
      setIsBusy(false)
    }
  }

  const average =
    observed?.average_actual_minutes != null ? Math.round(observed.average_actual_minutes) : null

  return (
    <div className="observed-route-time">
      <button type="button" onClick={() => void look()} disabled={isBusy}>
        Observed time
      </button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {observed && observed.sample_count === 0 && (
        <p className="status">No completed runs on this route yet.</p>
      )}
      {observed && average !== null && (
        <p className="status">
          Took {average} min on average over {observed.sample_count} run
          {observed.sample_count === 1 ? '' : 's'}
          {observed.most_recent_service_date && ` (latest ${observed.most_recent_service_date})`};
          planned {template.duration_minutes} min.{' '}
          {average !== template.duration_minutes && (
            <button type="button" onClick={() => void adopt(average)} disabled={isBusy}>
              Plan {average} minutes
            </button>
          )}
        </p>
      )}
    </div>
  )
}
