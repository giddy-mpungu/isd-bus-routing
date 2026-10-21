import { useId, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { School } from '../api/types'

/**
 * Spec section 3: a school's attendance zone, uploaded as GeoJSON from the
 * district's GIS (a Polygon or MultiPolygon, or a file holding one). Homes
 * outside it aren't eligible for the bus, except for specialized
 * transportation.
 */
export function SchoolZoneControl({
  school,
  onChanged,
}: {
  school: School
  onChanged: () => Promise<void>
}) {
  const id = useId()
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  async function act(work: () => Promise<unknown>) {
    setError(null)
    setIsBusy(true)
    try {
      await work()
      await onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to update the zone.')
    } finally {
      setIsBusy(false)
    }
  }

  async function handleFile(file: File | undefined) {
    if (!file) return
    let geojson: unknown
    try {
      geojson = JSON.parse(await file.text())
    } catch {
      setError("That file isn't GeoJSON.")
      return
    }
    await act(() => api.setSchoolZone(school.id, geojson))
  }

  return (
    <span className="school-zone">
      {school.has_zone ? ' Attendance zone on file.' : ' No attendance zone.'}{' '}
      <label htmlFor={`${id}-zone`}>
        {school.has_zone ? 'Replace' : 'Upload'} {school.name}&apos;s zone (GeoJSON)
      </label>
      <input
        id={`${id}-zone`}
        type="file"
        accept=".geojson,.json,application/geo+json,application/json"
        disabled={isBusy}
        onChange={(event) => void handleFile(event.target.files?.[0])}
      />
      {school.has_zone && (
        <button
          type="button"
          disabled={isBusy}
          onClick={() => void act(() => api.removeSchoolZone(school.id))}
        >
          Remove {school.name}&apos;s zone
        </button>
      )}
      {error && (
        <span role="alert" className="error">
          {' '}
          {error}
        </span>
      )}
    </span>
  )
}
