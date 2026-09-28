import { useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Stop, Student } from '../api/types'
import { LazyMapView } from '../components/LazyMapView'
import type { MapMarker } from '../components/MapView'

export function StopsSection({
  stops,
  students,
  canEdit,
  onChanged,
}: {
  stops: Stop[]
  students: Student[]
  canEdit: boolean
  onChanged: () => Promise<void>
}) {
  // --- Create form ---
  const [label, setLabel] = useState('')
  const [lat, setLat] = useState('')
  const [lon, setLon] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [isSavingCreate, setIsSavingCreate] = useState(false)

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    setCreateError(null)
    setIsSavingCreate(true)
    try {
      await api.createStop({ label, location_lat: Number(lat), location_lon: Number(lon) })
      setLabel('')
      setLat('')
      setLon('')
      await onChanged()
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create stop.')
    } finally {
      setIsSavingCreate(false)
    }
  }

  // --- Edit ("relocate") ---
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draftLabel, setDraftLabel] = useState('')
  const [draftLat, setDraftLat] = useState('')
  const [draftLon, setDraftLon] = useState('')
  const [rowError, setRowError] = useState<string | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  function startEdit(stop: Stop) {
    setEditingId(stop.id)
    setDraftLabel(stop.label)
    setDraftLat(String(stop.location_lat))
    setDraftLon(String(stop.location_lon))
    setRowError(null)
  }

  function cancelEdit() {
    setEditingId(null)
    setRowError(null)
  }

  async function handleSaveEdit(event: FormEvent) {
    event.preventDefault()
    if (editingId === null) return
    setRowError(null)
    setIsSavingEdit(true)
    try {
      await api.updateStop(editingId, {
        label: draftLabel,
        location_lat: Number(draftLat),
        location_lon: Number(draftLon),
      })
      cancelEdit()
      await onChanged()
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : 'Failed to relocate stop.')
    } finally {
      setIsSavingEdit(false)
    }
  }

  async function handleDelete(stop: Stop) {
    setRowError(null)
    setDeletingId(stop.id)
    try {
      await api.deleteStop(stop.id)
      await onChanged()
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : 'Failed to delete stop.')
    } finally {
      setDeletingId(null)
    }
  }

  // Spec section 3.1: place or relocate a stop by clicking the map. The
  // coordinate fields stay the keyboard-accessible way to do the same.
  function handlePick(pickedLat: number, pickedLon: number) {
    if (editingId !== null) {
      setDraftLat(String(pickedLat))
      setDraftLon(String(pickedLon))
    } else {
      setLat(String(pickedLat))
      setLon(String(pickedLon))
    }
  }

  const pickLat = editingId !== null ? draftLat : lat
  const pickLon = editingId !== null ? draftLon : lon
  const mapMarkers: MapMarker[] = [
    ...stops
      .filter((s) => s.id !== editingId)
      .map((s) => ({
        id: `stop-${s.id}`,
        lat: s.location_lat,
        lon: s.location_lon,
        label: s.label,
        tone: 'stop' as const,
      })),
    ...(pickLat !== '' &&
    pickLon !== '' &&
    Number.isFinite(Number(pickLat)) &&
    Number.isFinite(Number(pickLon))
      ? [
          {
            id: 'pick',
            lat: Number(pickLat),
            lon: Number(pickLon),
            label: editingId !== null ? `${draftLabel || 'Stop'} (new spot)` : label || 'New stop',
            tone: 'pick' as const,
          },
        ]
      : []),
  ]

  function studentsAt(stopId: number): number {
    return students.filter((s) => s.stop_id === stopId).length
  }

  return (
    <section className="stops-section">
      <h2>Stops</h2>
      {canEdit && (
        <p className="status">
          Click the map to set the coordinates of the stop you're adding or relocating.
        </p>
      )}
      <LazyMapView
        markers={mapMarkers}
        label="Stops map"
        onPick={canEdit ? handlePick : undefined}
      />
      {rowError && (
        <p role="alert" className="error">
          {rowError}
        </p>
      )}
      <ul>
        {stops.map((s) => {
          const inUse = studentsAt(s.id)
          return editingId === s.id ? (
            <li key={s.id}>
              <form onSubmit={(event) => void handleSaveEdit(event)}>
                <label htmlFor={`stop-edit-label-${s.id}`}>Stop label</label>
                <input
                  id={`stop-edit-label-${s.id}`}
                  value={draftLabel}
                  onChange={(event) => setDraftLabel(event.target.value)}
                  required
                />
                <label htmlFor={`stop-edit-lat-${s.id}`}>Stop latitude</label>
                <input
                  id={`stop-edit-lat-${s.id}`}
                  type="number"
                  step="any"
                  value={draftLat}
                  onChange={(event) => setDraftLat(event.target.value)}
                  required
                />
                <label htmlFor={`stop-edit-lon-${s.id}`}>Stop longitude</label>
                <input
                  id={`stop-edit-lon-${s.id}`}
                  type="number"
                  step="any"
                  value={draftLon}
                  onChange={(event) => setDraftLon(event.target.value)}
                  required
                />
                <button type="submit" disabled={isSavingEdit}>
                  {isSavingEdit ? 'Saving…' : 'Save'}
                </button>
                <button type="button" onClick={cancelEdit} disabled={isSavingEdit}>
                  Cancel
                </button>
              </form>
            </li>
          ) : (
            <li key={s.id}>
              {s.label} ({s.location_lat}, {s.location_lon})
              {inUse > 0 && ` — ${inUse} student(s) assigned`}
              {canEdit && (
                <>
                  {' '}
                  <button type="button" onClick={() => startEdit(s)}>
                    Relocate
                  </button>{' '}
                  <button
                    type="button"
                    onClick={() => void handleDelete(s)}
                    disabled={inUse > 0 || deletingId === s.id}
                    title={inUse > 0 ? 'Reassign the student(s) at this stop first' : undefined}
                  >
                    {deletingId === s.id ? 'Deleting…' : 'Delete'}
                  </button>
                </>
              )}
            </li>
          )
        })}
      </ul>
      {canEdit && (
        <form onSubmit={(event) => void handleCreate(event)}>
          <label htmlFor="stop-label">Stop label</label>
          <input
            id="stop-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            required
          />
          <label htmlFor="stop-lat">Stop latitude</label>
          <input
            id="stop-lat"
            type="number"
            step="any"
            value={lat}
            onChange={(event) => setLat(event.target.value)}
            required
          />
          <label htmlFor="stop-lon">Stop longitude</label>
          <input
            id="stop-lon"
            type="number"
            step="any"
            value={lon}
            onChange={(event) => setLon(event.target.value)}
            required
          />
          {createError && (
            <p role="alert" className="error">
              {createError}
            </p>
          )}
          <button type="submit" disabled={isSavingCreate}>
            {isSavingCreate ? 'Saving…' : 'Add stop'}
          </button>
        </form>
      )}
    </section>
  )
}
