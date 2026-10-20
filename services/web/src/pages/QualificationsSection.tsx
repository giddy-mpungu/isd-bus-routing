import { useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Qualification, QualificationKind } from '../api/types'
import { Badge } from '../components/Badge'

function qualificationLabel(q: Qualification): string {
  return q.description ? `${q.code} — ${q.description}` : q.code
}

export function QualificationsSection({
  qualifications,
  canEdit,
  onChanged,
}: {
  qualifications: Qualification[]
  canEdit: boolean
  onChanged: () => Promise<void>
}) {
  // --- Create form ---
  const [code, setCode] = useState('')
  const [kind, setKind] = useState<QualificationKind>('license')
  const [description, setDescription] = useState('')
  const [takesPosition, setTakesPosition] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [isSavingCreate, setIsSavingCreate] = useState(false)

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    setCreateError(null)
    setIsSavingCreate(true)
    try {
      await api.createQualification({
        code,
        kind,
        description: description || undefined,
        takes_wheelchair_position: kind === 'vehicle_capability' && takesPosition,
      })
      setCode('')
      setDescription('')
      setTakesPosition(false)
      await onChanged()
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create qualification.')
    } finally {
      setIsSavingCreate(false)
    }
  }

  // --- Edit (description only -- code/kind are immutable, see the
  // backend's QualificationUpdate docstring) ---
  const [editingId, setEditingId] = useState<number | null>(null)
  const [descriptionDraft, setDescriptionDraft] = useState('')
  const [editError, setEditError] = useState<string | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)

  function startEdit(q: Qualification) {
    setEditingId(q.id)
    setDescriptionDraft(q.description ?? '')
    setEditError(null)
  }

  function cancelEdit() {
    setEditingId(null)
    setEditError(null)
  }

  async function handleSaveEdit(event: FormEvent) {
    event.preventDefault()
    if (editingId === null) return
    setEditError(null)
    setIsSavingEdit(true)
    try {
      await api.updateQualification(editingId, { description: descriptionDraft })
      cancelEdit()
      await onChanged()
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Failed to save qualification.')
    } finally {
      setIsSavingEdit(false)
    }
  }

  async function handleToggleActive(q: Qualification) {
    setEditError(null)
    try {
      await api.updateQualification(q.id, { is_active: !q.is_active })
      await onChanged()
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Failed to update qualification.')
    }
  }

  return (
    <section className="qualifications-section">
      <h2>Qualifications</h2>
      {editError && (
        <p role="alert" className="error">
          {editError}
        </p>
      )}
      <ul>
        {qualifications.map((q) =>
          editingId === q.id ? (
            <li key={q.id}>
              <form onSubmit={(event) => void handleSaveEdit(event)}>
                <label htmlFor={`qual-edit-description-${q.id}`}>Description</label>
                <input
                  id={`qual-edit-description-${q.id}`}
                  value={descriptionDraft}
                  onChange={(event) => setDescriptionDraft(event.target.value)}
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
            <li key={q.id}>
              {qualificationLabel(q)} ({q.kind})
              {q.takes_wheelchair_position && ' — takes a wheelchair position'}{' '}
              {!q.is_active && <Badge tone="neutral">inactive</Badge>}
              {canEdit && (
                <>
                  {' '}
                  <button type="button" onClick={() => startEdit(q)}>
                    Edit
                  </button>{' '}
                  <button type="button" onClick={() => void handleToggleActive(q)}>
                    {q.is_active ? 'Deactivate' : 'Reactivate'}
                  </button>
                </>
              )}
            </li>
          ),
        )}
      </ul>
      {canEdit && (
        <form onSubmit={(event) => void handleCreate(event)}>
          <label htmlFor="qual-code">Code</label>
          <input
            id="qual-code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            required
          />
          <label htmlFor="qual-kind">Kind</label>
          <select
            id="qual-kind"
            value={kind}
            onChange={(event) => setKind(event.target.value as QualificationKind)}
          >
            <option value="license">license (driver)</option>
            <option value="vehicle_capability">vehicle_capability (vehicle)</option>
          </select>
          <label htmlFor="qual-description">Description</label>
          <input
            id="qual-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
          {kind === 'vehicle_capability' && (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={takesPosition}
                onChange={(event) => setTakesPosition(event.target.checked)}
              />
              Students who need this ride in their wheelchair (each takes a wheelchair position)
            </label>
          )}
          {createError && (
            <p role="alert" className="error">
              {createError}
            </p>
          )}
          <button type="submit" disabled={isSavingCreate}>
            {isSavingCreate ? 'Saving…' : 'Add qualification'}
          </button>
        </form>
      )}
    </section>
  )
}
