import { useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { School } from '../api/types'
import { SchoolZoneControl } from './SchoolZoneControl'

export function SchoolsSection({
  schools,
  canEdit,
  onChanged,
}: {
  schools: School[]
  canEdit: boolean
  onChanged: () => Promise<void>
}) {
  // --- Create form ---
  const [name, setName] = useState('')
  const [lat, setLat] = useState('')
  const [lon, setLon] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [isSavingCreate, setIsSavingCreate] = useState(false)

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    setCreateError(null)
    setIsSavingCreate(true)
    try {
      await api.createSchool({ name, location_lat: Number(lat), location_lon: Number(lon) })
      setName('')
      setLat('')
      setLon('')
      await onChanged()
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create school.')
    } finally {
      setIsSavingCreate(false)
    }
  }

  // --- Edit (name and location; the SIS id lives on the SIS import tab) ---
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draftName, setDraftName] = useState('')
  const [draftLat, setDraftLat] = useState('')
  const [draftLon, setDraftLon] = useState('')
  const [rowError, setRowError] = useState<string | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)

  function startEdit(school: School) {
    setEditingId(school.id)
    setDraftName(school.name)
    setDraftLat(String(school.location_lat))
    setDraftLon(String(school.location_lon))
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
      await api.updateSchool(editingId, {
        name: draftName,
        location_lat: Number(draftLat),
        location_lon: Number(draftLon),
      })
      cancelEdit()
      await onChanged()
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : 'Failed to save school.')
    } finally {
      setIsSavingEdit(false)
    }
  }

  return (
    <section className="schools-section">
      <h2>Schools</h2>
      {rowError && (
        <p role="alert" className="error">
          {rowError}
        </p>
      )}
      <ul>
        {schools.map((s) =>
          editingId === s.id ? (
            <li key={s.id}>
              <form onSubmit={(event) => void handleSaveEdit(event)}>
                <label htmlFor={`school-edit-name-${s.id}`}>School name</label>
                <input
                  id={`school-edit-name-${s.id}`}
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  required
                />
                <label htmlFor={`school-edit-lat-${s.id}`}>School latitude</label>
                <input
                  id={`school-edit-lat-${s.id}`}
                  type="number"
                  step="any"
                  value={draftLat}
                  onChange={(event) => setDraftLat(event.target.value)}
                  required
                />
                <label htmlFor={`school-edit-lon-${s.id}`}>School longitude</label>
                <input
                  id={`school-edit-lon-${s.id}`}
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
              {s.name} ({s.location_lat}, {s.location_lon})
              {canEdit && (
                <>
                  {' '}
                  <button type="button" onClick={() => startEdit(s)} aria-label={`Edit ${s.name}`}>
                    Edit
                  </button>
                  <SchoolZoneControl school={s} onChanged={onChanged} />
                </>
              )}
            </li>
          ),
        )}
      </ul>
      {canEdit && (
        <form onSubmit={(event) => void handleCreate(event)}>
          <label htmlFor="school-name">Name</label>
          <input
            id="school-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
          <label htmlFor="school-lat">Latitude</label>
          <input
            id="school-lat"
            type="number"
            step="any"
            value={lat}
            onChange={(event) => setLat(event.target.value)}
            required
          />
          <label htmlFor="school-lon">Longitude</label>
          <input
            id="school-lon"
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
            {isSavingCreate ? 'Saving…' : 'Add school'}
          </button>
        </form>
      )}
    </section>
  )
}
