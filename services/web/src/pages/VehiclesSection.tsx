import { useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { LicenseClass, Qualification, Vehicle, VehicleType } from '../api/types'
import { Badge } from '../components/Badge'
import { LICENSE_CLASSES, LICENSE_LABELS } from '../licenses'

const VEHICLE_TYPES: { value: VehicleType; label: string }[] = [
  { value: 'type_a', label: 'Type A (small, van chassis)' },
  { value: 'type_b', label: 'Type B' },
  { value: 'type_c', label: 'Type C (conventional)' },
  { value: 'type_d', label: 'Type D (transit style)' },
  { value: 'van', label: 'Van' },
  { value: 'other', label: 'Other' },
]
const TYPE_LABELS = Object.fromEntries(VEHICLE_TYPES.map((t) => [t.value, t.label])) as Record<
  VehicleType,
  string
>

function qualificationLabel(q: Qualification): string {
  return q.description ? `${q.code} — ${q.description}` : q.code
}

interface DraftFields {
  label: string
  nominal_capacity: string
  effective_capacity: string
  length_m: string
  width_m: string
  height_m: string
  weight_kg: string
  vehicle_type: VehicleType | ''
  wheelchair_positions: string
  turning_radius_m: string
  yard_lat: string
  yard_lon: string
  required_license_class: LicenseClass
  qualification_codes: Set<string>
}

function draftFrom(v: Vehicle): DraftFields {
  return {
    label: v.label,
    nominal_capacity: v.nominal_capacity != null ? String(v.nominal_capacity) : '',
    effective_capacity: v.effective_capacity != null ? String(v.effective_capacity) : '',
    length_m: v.length_m != null ? String(v.length_m) : '',
    width_m: v.width_m != null ? String(v.width_m) : '',
    height_m: v.height_m != null ? String(v.height_m) : '',
    weight_kg: v.weight_kg != null ? String(v.weight_kg) : '',
    vehicle_type: v.vehicle_type ?? '',
    wheelchair_positions: v.wheelchair_positions != null ? String(v.wheelchair_positions) : '',
    turning_radius_m: v.turning_radius_m != null ? String(v.turning_radius_m) : '',
    yard_lat: v.yard_lat != null ? String(v.yard_lat) : '',
    yard_lon: v.yard_lon != null ? String(v.yard_lon) : '',
    required_license_class: v.required_license_class,
    qualification_codes: new Set(v.qualifications.map((q) => q.code)),
  }
}

export function VehiclesSection({
  vehicles,
  qualifications,
  canEdit,
  onChanged,
}: {
  vehicles: Vehicle[]
  qualifications: Qualification[]
  canEdit: boolean
  onChanged: () => Promise<void>
}) {
  const vehicleQualifications = qualifications.filter(
    (q) => q.kind === 'vehicle_capability' && q.is_active,
  )

  // --- Create form ---
  const [label, setLabel] = useState('')
  const [nominalCapacity, setNominalCapacity] = useState('')
  const [effectiveCapacity, setEffectiveCapacity] = useState('')
  const [length, setLength] = useState('')
  const [width, setWidth] = useState('')
  const [height, setHeight] = useState('')
  const [weight, setWeight] = useState('')
  const [vehicleType, setVehicleType] = useState<VehicleType | ''>('')
  const [wheelchairPositions, setWheelchairPositions] = useState('')
  const [turningRadius, setTurningRadius] = useState('')
  const [yardLat, setYardLat] = useState('')
  const [yardLon, setYardLon] = useState('')
  const [requiredLicense, setRequiredLicense] = useState<LicenseClass | ''>('')
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
      await api.createVehicle({
        label,
        nominal_capacity: nominalCapacity ? Number(nominalCapacity) : undefined,
        effective_capacity: effectiveCapacity ? Number(effectiveCapacity) : undefined,
        length_m: length ? Number(length) : undefined,
        width_m: width ? Number(width) : undefined,
        height_m: height ? Number(height) : undefined,
        weight_kg: weight ? Number(weight) : undefined,
        vehicle_type: vehicleType || undefined,
        wheelchair_positions: wheelchairPositions ? Number(wheelchairPositions) : undefined,
        turning_radius_m: turningRadius ? Number(turningRadius) : undefined,
        yard_lat: yardLat ? Number(yardLat) : undefined,
        yard_lon: yardLon ? Number(yardLon) : undefined,
        qualification_codes: Array.from(qualCodes),
        required_license_class: requiredLicense || undefined,
      })
      setLabel('')
      setNominalCapacity('')
      setEffectiveCapacity('')
      setLength('')
      setWidth('')
      setHeight('')
      setWeight('')
      setVehicleType('')
      setWheelchairPositions('')
      setTurningRadius('')
      setYardLat('')
      setYardLon('')
      setRequiredLicense('')
      setQualCodes(new Set())
      await onChanged()
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create vehicle.')
    } finally {
      setIsSavingCreate(false)
    }
  }

  // --- Edit ---
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState<DraftFields | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)

  function startEdit(vehicle: Vehicle) {
    setEditingId(vehicle.id)
    setDraft(draftFrom(vehicle))
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
      await api.updateVehicle(editingId, {
        label: draft.label,
        nominal_capacity: draft.nominal_capacity ? Number(draft.nominal_capacity) : undefined,
        effective_capacity: draft.effective_capacity ? Number(draft.effective_capacity) : undefined,
        length_m: draft.length_m ? Number(draft.length_m) : undefined,
        width_m: draft.width_m ? Number(draft.width_m) : undefined,
        height_m: draft.height_m ? Number(draft.height_m) : undefined,
        weight_kg: draft.weight_kg ? Number(draft.weight_kg) : undefined,
        vehicle_type: draft.vehicle_type || null,
        wheelchair_positions: draft.wheelchair_positions
          ? Number(draft.wheelchair_positions)
          : null,
        turning_radius_m: draft.turning_radius_m ? Number(draft.turning_radius_m) : null,
        yard_lat: draft.yard_lat ? Number(draft.yard_lat) : null,
        yard_lon: draft.yard_lon ? Number(draft.yard_lon) : null,
        qualification_codes: Array.from(draft.qualification_codes),
        required_license_class: draft.required_license_class,
      })
      cancelEdit()
      await onChanged()
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Failed to save vehicle.')
    } finally {
      setIsSavingEdit(false)
    }
  }

  async function handleToggleActive(vehicle: Vehicle) {
    setEditError(null)
    try {
      await api.updateVehicle(vehicle.id, { is_active: !vehicle.is_active })
      await onChanged()
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Failed to update vehicle.')
    }
  }

  return (
    <section className="vehicles-section">
      <h2>Vehicles</h2>
      {editError && (
        <p role="alert" className="error">
          {editError}
        </p>
      )}
      <ul>
        {vehicles.map((v) =>
          editingId === v.id && draft ? (
            <li key={v.id}>
              <form onSubmit={(event) => void handleSaveEdit(event)}>
                <label htmlFor={`vehicle-edit-label-${v.id}`}>Label</label>
                <input
                  id={`vehicle-edit-label-${v.id}`}
                  value={draft.label}
                  onChange={(event) => setDraft({ ...draft, label: event.target.value })}
                  required
                />
                <label htmlFor={`vehicle-edit-nominal-${v.id}`}>Nominal capacity</label>
                <input
                  id={`vehicle-edit-nominal-${v.id}`}
                  type="number"
                  min="1"
                  value={draft.nominal_capacity}
                  onChange={(event) => setDraft({ ...draft, nominal_capacity: event.target.value })}
                />
                <label htmlFor={`vehicle-edit-effective-${v.id}`}>Effective capacity</label>
                <input
                  id={`vehicle-edit-effective-${v.id}`}
                  type="number"
                  min="1"
                  value={draft.effective_capacity}
                  onChange={(event) =>
                    setDraft({ ...draft, effective_capacity: event.target.value })
                  }
                />
                <label htmlFor={`vehicle-edit-length-${v.id}`}>Length (m)</label>
                <input
                  id={`vehicle-edit-length-${v.id}`}
                  type="number"
                  step="any"
                  min="0.01"
                  value={draft.length_m}
                  onChange={(event) => setDraft({ ...draft, length_m: event.target.value })}
                />
                <label htmlFor={`vehicle-edit-width-${v.id}`}>Width (m)</label>
                <input
                  id={`vehicle-edit-width-${v.id}`}
                  type="number"
                  step="any"
                  min="0.01"
                  value={draft.width_m}
                  onChange={(event) => setDraft({ ...draft, width_m: event.target.value })}
                />
                <label htmlFor={`vehicle-edit-height-${v.id}`}>Height (m)</label>
                <input
                  id={`vehicle-edit-height-${v.id}`}
                  type="number"
                  step="any"
                  min="0.01"
                  value={draft.height_m}
                  onChange={(event) => setDraft({ ...draft, height_m: event.target.value })}
                />
                <label htmlFor={`vehicle-edit-weight-${v.id}`}>Weight (kg)</label>
                <input
                  id={`vehicle-edit-weight-${v.id}`}
                  type="number"
                  step="any"
                  min="0.01"
                  value={draft.weight_kg}
                  onChange={(event) => setDraft({ ...draft, weight_kg: event.target.value })}
                />
                <label htmlFor={`vehicle-edit-type-${v.id}`}>Vehicle type</label>
                <select
                  id={`vehicle-edit-type-${v.id}`}
                  value={draft.vehicle_type}
                  onChange={(event) =>
                    setDraft({ ...draft, vehicle_type: event.target.value as VehicleType | '' })
                  }
                >
                  <option value="">Not recorded</option>
                  {VEHICLE_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
                <label htmlFor={`vehicle-edit-wheelchair-${v.id}`}>Wheelchair positions</label>
                <input
                  id={`vehicle-edit-wheelchair-${v.id}`}
                  type="number"
                  min="0"
                  max="20"
                  value={draft.wheelchair_positions}
                  onChange={(event) =>
                    setDraft({ ...draft, wheelchair_positions: event.target.value })
                  }
                />
                <label htmlFor={`vehicle-edit-turning-${v.id}`}>Turning radius (m)</label>
                <input
                  id={`vehicle-edit-turning-${v.id}`}
                  type="number"
                  step="any"
                  min="0.1"
                  max="40"
                  value={draft.turning_radius_m}
                  onChange={(event) => setDraft({ ...draft, turning_radius_m: event.target.value })}
                />
                <label htmlFor={`vehicle-edit-yard-lat-${v.id}`}>Yard latitude</label>
                <input
                  id={`vehicle-edit-yard-lat-${v.id}`}
                  type="number"
                  step="any"
                  min="-90"
                  max="90"
                  value={draft.yard_lat}
                  onChange={(event) => setDraft({ ...draft, yard_lat: event.target.value })}
                />
                <label htmlFor={`vehicle-edit-yard-lon-${v.id}`}>Yard longitude</label>
                <input
                  id={`vehicle-edit-yard-lon-${v.id}`}
                  type="number"
                  step="any"
                  min="-180"
                  max="180"
                  value={draft.yard_lon}
                  onChange={(event) => setDraft({ ...draft, yard_lon: event.target.value })}
                />
                <label htmlFor={`vehicle-edit-license-${v.id}`}>Required license</label>
                <select
                  id={`vehicle-edit-license-${v.id}`}
                  value={draft.required_license_class}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      required_license_class: event.target.value as LicenseClass,
                    })
                  }
                >
                  {LICENSE_CLASSES.map((c) => (
                    <option key={c} value={c}>
                      {LICENSE_LABELS[c]}
                    </option>
                  ))}
                </select>
                {vehicleQualifications.length > 0 && (
                  <fieldset>
                    <legend>Vehicle capability qualifications</legend>
                    {vehicleQualifications.map((q) => (
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
            <li key={v.id}>
              {v.label}
              {v.nominal_capacity != null && ` — capacity ${v.nominal_capacity}`}
              {` — needs ${LICENSE_LABELS[v.required_license_class]}`}
              {(v.length_m != null || v.width_m != null || v.height_m != null) &&
                ` — ${v.length_m ?? '?'}m × ${v.width_m ?? '?'}m × ${v.height_m ?? '?'}m`}
              {v.weight_kg != null && ` — ${v.weight_kg}kg`}
              {v.vehicle_type != null && ` — ${TYPE_LABELS[v.vehicle_type]}`}
              {v.wheelchair_positions != null &&
                ` — ${v.wheelchair_positions} wheelchair position${v.wheelchair_positions === 1 ? '' : 's'}`}
              {v.turning_radius_m != null && ` — turns in ${v.turning_radius_m}m`}
              {v.yard_lat != null &&
                v.yard_lon != null &&
                ` — parks at ${v.yard_lat.toFixed(4)}, ${v.yard_lon.toFixed(4)}`}
              {v.qualifications.length > 0 &&
                ` (${v.qualifications.map((q) => q.code).join(', ')})`}
              {!v.is_active && (
                <>
                  {' '}
                  <Badge tone="neutral">inactive</Badge>
                </>
              )}
              {canEdit && (
                <>
                  {' '}
                  <button type="button" onClick={() => startEdit(v)}>
                    Edit
                  </button>{' '}
                  <button type="button" onClick={() => void handleToggleActive(v)}>
                    {v.is_active ? 'Deactivate' : 'Reactivate'}
                  </button>
                </>
              )}
            </li>
          ),
        )}
      </ul>
      {canEdit && (
        <form onSubmit={(event) => void handleCreate(event)}>
          <label htmlFor="vehicle-label">Label</label>
          <input
            id="vehicle-label"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            required
          />
          <label htmlFor="vehicle-nominal-capacity">Nominal capacity (optional)</label>
          <input
            id="vehicle-nominal-capacity"
            type="number"
            min="1"
            value={nominalCapacity}
            onChange={(event) => setNominalCapacity(event.target.value)}
          />
          <label htmlFor="vehicle-effective-capacity">Effective capacity (optional)</label>
          <input
            id="vehicle-effective-capacity"
            type="number"
            min="1"
            value={effectiveCapacity}
            onChange={(event) => setEffectiveCapacity(event.target.value)}
          />
          <label htmlFor="vehicle-length">Length in meters (optional)</label>
          <input
            id="vehicle-length"
            type="number"
            step="any"
            min="0.01"
            value={length}
            onChange={(event) => setLength(event.target.value)}
          />
          <label htmlFor="vehicle-width">Width in meters (optional)</label>
          <input
            id="vehicle-width"
            type="number"
            step="any"
            min="0.01"
            value={width}
            onChange={(event) => setWidth(event.target.value)}
          />
          <label htmlFor="vehicle-height">Height in meters (optional)</label>
          <input
            id="vehicle-height"
            type="number"
            step="any"
            min="0.01"
            value={height}
            onChange={(event) => setHeight(event.target.value)}
          />
          <label htmlFor="vehicle-weight">Weight in kg (optional)</label>
          <input
            id="vehicle-weight"
            type="number"
            step="any"
            min="0.01"
            value={weight}
            onChange={(event) => setWeight(event.target.value)}
          />
          <label htmlFor="vehicle-type">Vehicle type (optional)</label>
          <select
            id="vehicle-type"
            value={vehicleType}
            onChange={(event) => setVehicleType(event.target.value as VehicleType | '')}
          >
            <option value="">Not recorded</option>
            {VEHICLE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <label htmlFor="vehicle-wheelchair-positions">Wheelchair positions (optional)</label>
          <input
            id="vehicle-wheelchair-positions"
            type="number"
            min="0"
            max="20"
            value={wheelchairPositions}
            onChange={(event) => setWheelchairPositions(event.target.value)}
          />
          <label htmlFor="vehicle-turning-radius">Turning radius in meters (optional)</label>
          <input
            id="vehicle-turning-radius"
            type="number"
            step="any"
            min="0.1"
            max="40"
            value={turningRadius}
            onChange={(event) => setTurningRadius(event.target.value)}
          />
          <label htmlFor="vehicle-yard-lat">Yard latitude (optional)</label>
          <input
            id="vehicle-yard-lat"
            type="number"
            step="any"
            min="-90"
            max="90"
            value={yardLat}
            onChange={(event) => setYardLat(event.target.value)}
            aria-describedby="vehicle-yard-help"
          />
          <label htmlFor="vehicle-yard-lon">Yard longitude (optional)</label>
          <input
            id="vehicle-yard-lon"
            type="number"
            step="any"
            min="-180"
            max="180"
            value={yardLon}
            onChange={(event) => setYardLon(event.target.value)}
            aria-describedby="vehicle-yard-help"
          />
          <small id="vehicle-yard-help">
            Where it parks overnight. With both, scheduling counts the drive out to its first run
            and back.
          </small>
          <label htmlFor="vehicle-required-license">Required license</label>
          <select
            id="vehicle-required-license"
            value={requiredLicense}
            onChange={(event) => setRequiredLicense(event.target.value as LicenseClass | '')}
          >
            <option value="">Automatic: CDL B for 15+ passengers or unknown, else Class C</option>
            {LICENSE_CLASSES.map((c) => (
              <option key={c} value={c}>
                {LICENSE_LABELS[c]}
              </option>
            ))}
          </select>
          {vehicleQualifications.length > 0 && (
            <fieldset>
              <legend>Vehicle capability qualifications</legend>
              {vehicleQualifications.map((q) => (
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
            {isSavingCreate ? 'Saving…' : 'Add vehicle'}
          </button>
        </form>
      )}
    </section>
  )
}
