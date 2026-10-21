import { useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Driver, LicenseClass, Qualification } from '../api/types'
import { Badge } from '../components/Badge'
import { LICENSE_CLASSES, LICENSE_LABELS } from '../licenses'

function qualificationLabel(q: Qualification): string {
  return q.description ? `${q.code} — ${q.description}` : q.code
}

interface DraftFields {
  full_name: string
  employee_id: string
  max_continuous_minutes: string
  license_class: LicenseClass | ''
  qualification_codes: Set<string>
}

function draftFrom(d: Driver): DraftFields {
  return {
    full_name: d.full_name,
    employee_id: d.employee_id ?? '',
    max_continuous_minutes:
      d.max_continuous_minutes != null ? String(d.max_continuous_minutes) : '',
    license_class: d.license_class ?? '',
    qualification_codes: new Set(d.qualifications.map((q) => q.code)),
  }
}

export function DriversSection({
  drivers,
  qualifications,
  canEdit,
  onChanged,
}: {
  drivers: Driver[]
  qualifications: Qualification[]
  canEdit: boolean
  onChanged: () => Promise<void>
}) {
  const licenseQualifications = qualifications.filter((q) => q.kind === 'license' && q.is_active)

  // --- Create form ---
  const [fullName, setFullName] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [maxContinuous, setMaxContinuous] = useState('')
  const [licenseClass, setLicenseClass] = useState<LicenseClass | ''>('')
  const [qualCodes, setQualCodes] = useState<Set<string>>(new Set())
  const [createError, setCreateError] = useState<string | null>(null)
  const [isSavingCreate, setIsSavingCreate] = useState(false)

  function toggleCreateQual(code: string) {
    setQualCodes((prev) => {
      const next = new Set(prev)
      if (next.has(code)) {
        next.delete(code)
      } else {
        next.add(code)
      }
      return next
    })
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    setCreateError(null)
    setIsSavingCreate(true)
    try {
      await api.createDriver({
        full_name: fullName,
        employee_id: employeeId.trim() || undefined,
        max_continuous_minutes: maxContinuous ? Number(maxContinuous) : undefined,
        qualification_codes: Array.from(qualCodes),
        license_class: licenseClass || undefined,
      })
      setFullName('')
      setEmployeeId('')
      setMaxContinuous('')
      setLicenseClass('')
      setQualCodes(new Set())
      await onChanged()
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create driver.')
    } finally {
      setIsSavingCreate(false)
    }
  }

  // --- Edit ---
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState<DraftFields | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)

  function startEdit(driver: Driver) {
    setEditingId(driver.id)
    setDraft(draftFrom(driver))
    setEditError(null)
  }

  function cancelEdit() {
    setEditingId(null)
    setDraft(null)
    setEditError(null)
  }

  function toggleEditQual(code: string) {
    setDraft((prev) => {
      if (!prev) return prev
      const next = new Set(prev.qualification_codes)
      if (next.has(code)) {
        next.delete(code)
      } else {
        next.add(code)
      }
      return { ...prev, qualification_codes: next }
    })
  }

  async function handleSaveEdit(event: FormEvent) {
    event.preventDefault()
    if (editingId === null || !draft) return
    setEditError(null)
    setIsSavingEdit(true)
    try {
      await api.updateDriver(editingId, {
        full_name: draft.full_name,
        employee_id: draft.employee_id.trim() || null,
        max_continuous_minutes: draft.max_continuous_minutes
          ? Number(draft.max_continuous_minutes)
          : undefined,
        qualification_codes: Array.from(draft.qualification_codes),
        license_class: draft.license_class || null,
      })
      cancelEdit()
      await onChanged()
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Failed to save driver.')
    } finally {
      setIsSavingEdit(false)
    }
  }

  async function handleToggleActive(driver: Driver) {
    setEditError(null)
    try {
      await api.updateDriver(driver.id, { is_active: !driver.is_active })
      await onChanged()
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Failed to update driver.')
    }
  }

  return (
    <section className="drivers-section">
      <h2>Drivers</h2>
      {editError && (
        <p role="alert" className="error">
          {editError}
        </p>
      )}
      <ul>
        {drivers.map((d) =>
          editingId === d.id && draft ? (
            <li key={d.id}>
              <form onSubmit={(event) => void handleSaveEdit(event)}>
                <label htmlFor={`driver-edit-name-${d.id}`}>Full name</label>
                <input
                  id={`driver-edit-name-${d.id}`}
                  value={draft.full_name}
                  onChange={(event) => setDraft({ ...draft, full_name: event.target.value })}
                  required
                />
                <label htmlFor={`driver-edit-employee-${d.id}`}>Employee ID</label>
                <input
                  id={`driver-edit-employee-${d.id}`}
                  value={draft.employee_id}
                  maxLength={64}
                  onChange={(event) => setDraft({ ...draft, employee_id: event.target.value })}
                />
                <label htmlFor={`driver-edit-max-${d.id}`}>Max continuous minutes</label>
                <input
                  id={`driver-edit-max-${d.id}`}
                  type="number"
                  min="1"
                  value={draft.max_continuous_minutes}
                  onChange={(event) =>
                    setDraft({ ...draft, max_continuous_minutes: event.target.value })
                  }
                />
                <label htmlFor={`driver-edit-license-${d.id}`}>License class</label>
                <select
                  id={`driver-edit-license-${d.id}`}
                  value={draft.license_class}
                  onChange={(event) =>
                    setDraft({ ...draft, license_class: event.target.value as LicenseClass | '' })
                  }
                >
                  <option value="">Not on record</option>
                  {LICENSE_CLASSES.map((c) => (
                    <option key={c} value={c}>
                      {LICENSE_LABELS[c]}
                    </option>
                  ))}
                </select>
                {licenseQualifications.length > 0 && (
                  <fieldset>
                    <legend>License qualifications</legend>
                    {licenseQualifications.map((q) => (
                      <label key={q.id} className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={draft.qualification_codes.has(q.code)}
                          onChange={() => toggleEditQual(q.code)}
                        />
                        {qualificationLabel(q)}
                      </label>
                    ))}
                  </fieldset>
                )}
                <button type="submit" disabled={isSavingEdit}>
                  {isSavingEdit ? 'Saving…' : 'Save'}
                </button>
                <button type="button" onClick={cancelEdit} disabled={isSavingEdit}>
                  Cancel
                </button>
              </form>
            </li>
          ) : (
            <li key={d.id}>
              {d.full_name}
              {d.employee_id && ` (${d.employee_id})`}
              {' — '}
              {d.license_class ? (
                LICENSE_LABELS[d.license_class]
              ) : (
                <Badge tone="warning">no license on record</Badge>
              )}
              {d.qualifications.length > 0 &&
                ` (${d.qualifications.map((q) => q.code).join(', ')})`}
              {!d.is_active && (
                <>
                  {' '}
                  <Badge tone="neutral">inactive</Badge>
                </>
              )}
              {canEdit && (
                <>
                  {' '}
                  <button type="button" onClick={() => startEdit(d)}>
                    Edit
                  </button>{' '}
                  <button type="button" onClick={() => void handleToggleActive(d)}>
                    {d.is_active ? 'Deactivate' : 'Reactivate'}
                  </button>
                </>
              )}
            </li>
          ),
        )}
      </ul>
      {canEdit && (
        <form onSubmit={(event) => void handleCreate(event)}>
          <label htmlFor="driver-name">Full name</label>
          <input
            id="driver-name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            required
          />
          <label htmlFor="driver-employee-id">Employee ID (optional, from HR)</label>
          <input
            id="driver-employee-id"
            value={employeeId}
            maxLength={64}
            onChange={(event) => setEmployeeId(event.target.value)}
          />
          <label htmlFor="driver-max-continuous">Max continuous minutes (optional)</label>
          <input
            id="driver-max-continuous"
            type="number"
            min="1"
            value={maxContinuous}
            onChange={(event) => setMaxContinuous(event.target.value)}
          />
          <label htmlFor="driver-license-class">License class</label>
          <select
            id="driver-license-class"
            value={licenseClass}
            onChange={(event) => setLicenseClass(event.target.value as LicenseClass | '')}
          >
            <option value="">From a license qualification below, if any</option>
            {LICENSE_CLASSES.map((c) => (
              <option key={c} value={c}>
                {LICENSE_LABELS[c]}
              </option>
            ))}
          </select>
          <small>
            A driver may drive any vehicle at or below their class. Without one on record they
            can&apos;t be scheduled.
          </small>
          {licenseQualifications.length > 0 && (
            <fieldset>
              <legend>License qualifications</legend>
              {licenseQualifications.map((q) => (
                <label key={q.id} className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={qualCodes.has(q.code)}
                    onChange={() => toggleCreateQual(q.code)}
                  />
                  {qualificationLabel(q)}
                </label>
              ))}
            </fieldset>
          )}
          {createError && (
            <p role="alert" className="error">
              {createError}
            </p>
          )}
          <button type="submit" disabled={isSavingCreate}>
            {isSavingCreate ? 'Saving…' : 'Add driver'}
          </button>
        </form>
      )}
    </section>
  )
}
