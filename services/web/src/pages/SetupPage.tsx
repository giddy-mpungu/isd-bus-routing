import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Driver, Qualification, QualificationKind, School, Vehicle } from '../api/types'
import { useAuth } from '../auth/AuthContext'

// Creating a school/qualification/driver/vehicle is transportation_admin
// only (services/api/src/isd_api/routers/{schools,qualifications,drivers,
// vehicles}.py) — dispatcher can read all four lists but sees no create
// forms here, matching what the backend would reject anyway.

function qualificationLabel(q: Qualification): string {
  return q.description ? `${q.code} — ${q.description}` : q.code
}

export function SetupPage() {
  const { user } = useAuth()
  const canCreate = user?.role === 'transportation_admin'

  const [schools, setSchools] = useState<School[]>([])
  const [qualifications, setQualifications] = useState<Qualification[]>([])
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const loadAll = useCallback(async () => {
    setErrorMessage(null)
    try {
      const [schoolsData, qualificationsData, driversData, vehiclesData] = await Promise.all([
        api.getSchools(),
        api.getQualifications(),
        api.getDrivers(),
        api.getVehicles(),
      ])
      setSchools(schoolsData)
      setQualifications(qualificationsData)
      setDrivers(driversData)
      setVehicles(vehiclesData)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to load setup data.')
    }
  }, [])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const licenseQualifications = qualifications.filter((q) => q.kind === 'license')
  const vehicleQualifications = qualifications.filter((q) => q.kind === 'vehicle_capability')

  // --- Schools ---
  const [schoolName, setSchoolName] = useState('')
  const [schoolLat, setSchoolLat] = useState('')
  const [schoolLon, setSchoolLon] = useState('')
  const [schoolError, setSchoolError] = useState<string | null>(null)
  const [isSavingSchool, setIsSavingSchool] = useState(false)

  async function handleCreateSchool(event: FormEvent) {
    event.preventDefault()
    setSchoolError(null)
    setIsSavingSchool(true)
    try {
      await api.createSchool({
        name: schoolName,
        location_lat: Number(schoolLat),
        location_lon: Number(schoolLon),
      })
      setSchoolName('')
      setSchoolLat('')
      setSchoolLon('')
      await loadAll()
    } catch (err) {
      setSchoolError(err instanceof ApiError ? err.message : 'Failed to create school.')
    } finally {
      setIsSavingSchool(false)
    }
  }

  // --- Qualifications ---
  const [qualCode, setQualCode] = useState('')
  const [qualKind, setQualKind] = useState<QualificationKind>('license')
  const [qualDescription, setQualDescription] = useState('')
  const [qualError, setQualError] = useState<string | null>(null)
  const [isSavingQual, setIsSavingQual] = useState(false)

  async function handleCreateQualification(event: FormEvent) {
    event.preventDefault()
    setQualError(null)
    setIsSavingQual(true)
    try {
      await api.createQualification({
        code: qualCode,
        kind: qualKind,
        description: qualDescription || undefined,
      })
      setQualCode('')
      setQualDescription('')
      await loadAll()
    } catch (err) {
      setQualError(err instanceof ApiError ? err.message : 'Failed to create qualification.')
    } finally {
      setIsSavingQual(false)
    }
  }

  // --- Drivers ---
  const [driverName, setDriverName] = useState('')
  const [driverMaxContinuous, setDriverMaxContinuous] = useState('')
  const [driverQualCodes, setDriverQualCodes] = useState<Set<string>>(new Set())
  const [driverError, setDriverError] = useState<string | null>(null)
  const [isSavingDriver, setIsSavingDriver] = useState(false)

  function toggleDriverQual(code: string) {
    setDriverQualCodes((prev) => {
      const next = new Set(prev)
      if (next.has(code)) {
        next.delete(code)
      } else {
        next.add(code)
      }
      return next
    })
  }

  async function handleCreateDriver(event: FormEvent) {
    event.preventDefault()
    setDriverError(null)
    setIsSavingDriver(true)
    try {
      await api.createDriver({
        full_name: driverName,
        max_continuous_minutes: driverMaxContinuous ? Number(driverMaxContinuous) : undefined,
        qualification_codes: Array.from(driverQualCodes),
      })
      setDriverName('')
      setDriverMaxContinuous('')
      setDriverQualCodes(new Set())
      await loadAll()
    } catch (err) {
      setDriverError(err instanceof ApiError ? err.message : 'Failed to create driver.')
    } finally {
      setIsSavingDriver(false)
    }
  }

  // --- Vehicles ---
  const [vehicleLabel, setVehicleLabel] = useState('')
  const [vehicleNominalCapacity, setVehicleNominalCapacity] = useState('')
  const [vehicleEffectiveCapacity, setVehicleEffectiveCapacity] = useState('')
  const [vehicleQualCodes, setVehicleQualCodes] = useState<Set<string>>(new Set())
  const [vehicleError, setVehicleError] = useState<string | null>(null)
  const [isSavingVehicle, setIsSavingVehicle] = useState(false)

  function toggleVehicleQual(code: string) {
    setVehicleQualCodes((prev) => {
      const next = new Set(prev)
      if (next.has(code)) {
        next.delete(code)
      } else {
        next.add(code)
      }
      return next
    })
  }

  async function handleCreateVehicle(event: FormEvent) {
    event.preventDefault()
    setVehicleError(null)
    setIsSavingVehicle(true)
    try {
      await api.createVehicle({
        label: vehicleLabel,
        nominal_capacity: vehicleNominalCapacity ? Number(vehicleNominalCapacity) : undefined,
        effective_capacity: vehicleEffectiveCapacity ? Number(vehicleEffectiveCapacity) : undefined,
        qualification_codes: Array.from(vehicleQualCodes),
      })
      setVehicleLabel('')
      setVehicleNominalCapacity('')
      setVehicleEffectiveCapacity('')
      setVehicleQualCodes(new Set())
      await loadAll()
    } catch (err) {
      setVehicleError(err instanceof ApiError ? err.message : 'Failed to create vehicle.')
    } finally {
      setIsSavingVehicle(false)
    }
  }

  return (
    <main className="setup-page">
      {errorMessage && (
        <p role="alert" className="error">
          {errorMessage}
        </p>
      )}

      <section>
        <h2>Schools</h2>
        <ul>
          {schools.map((s) => (
            <li key={s.id}>
              {s.name} ({s.location_lat}, {s.location_lon})
            </li>
          ))}
        </ul>
        {canCreate && (
          <form onSubmit={(event) => void handleCreateSchool(event)}>
            <label htmlFor="school-name">Name</label>
            <input
              id="school-name"
              value={schoolName}
              onChange={(event) => setSchoolName(event.target.value)}
              required
            />
            <label htmlFor="school-lat">Latitude</label>
            <input
              id="school-lat"
              type="number"
              step="any"
              value={schoolLat}
              onChange={(event) => setSchoolLat(event.target.value)}
              required
            />
            <label htmlFor="school-lon">Longitude</label>
            <input
              id="school-lon"
              type="number"
              step="any"
              value={schoolLon}
              onChange={(event) => setSchoolLon(event.target.value)}
              required
            />
            {schoolError && (
              <p role="alert" className="error">
                {schoolError}
              </p>
            )}
            <button type="submit" disabled={isSavingSchool}>
              {isSavingSchool ? 'Saving…' : 'Add school'}
            </button>
          </form>
        )}
      </section>

      <section>
        <h2>Qualifications</h2>
        <ul>
          {qualifications.map((q) => (
            <li key={q.id}>
              {qualificationLabel(q)} ({q.kind})
            </li>
          ))}
        </ul>
        {canCreate && (
          <form onSubmit={(event) => void handleCreateQualification(event)}>
            <label htmlFor="qual-code">Code</label>
            <input
              id="qual-code"
              value={qualCode}
              onChange={(event) => setQualCode(event.target.value)}
              required
            />
            <label htmlFor="qual-kind">Kind</label>
            <select
              id="qual-kind"
              value={qualKind}
              onChange={(event) => setQualKind(event.target.value as QualificationKind)}
            >
              <option value="license">license (driver)</option>
              <option value="vehicle_capability">vehicle_capability (vehicle)</option>
            </select>
            <label htmlFor="qual-description">Description</label>
            <input
              id="qual-description"
              value={qualDescription}
              onChange={(event) => setQualDescription(event.target.value)}
            />
            {qualError && (
              <p role="alert" className="error">
                {qualError}
              </p>
            )}
            <button type="submit" disabled={isSavingQual}>
              {isSavingQual ? 'Saving…' : 'Add qualification'}
            </button>
          </form>
        )}
      </section>

      <section>
        <h2>Drivers</h2>
        <ul>
          {drivers.map((d) => (
            <li key={d.id}>
              {d.full_name}
              {d.qualifications.length > 0 &&
                ` (${d.qualifications.map((q) => q.code).join(', ')})`}
            </li>
          ))}
        </ul>
        {canCreate && (
          <form onSubmit={(event) => void handleCreateDriver(event)}>
            <label htmlFor="driver-name">Full name</label>
            <input
              id="driver-name"
              value={driverName}
              onChange={(event) => setDriverName(event.target.value)}
              required
            />
            <label htmlFor="driver-max-continuous">Max continuous minutes (optional)</label>
            <input
              id="driver-max-continuous"
              type="number"
              min="1"
              value={driverMaxContinuous}
              onChange={(event) => setDriverMaxContinuous(event.target.value)}
            />
            {licenseQualifications.length > 0 && (
              <fieldset>
                <legend>License qualifications</legend>
                {licenseQualifications.map((q) => (
                  <label key={q.id} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={driverQualCodes.has(q.code)}
                      onChange={() => toggleDriverQual(q.code)}
                    />
                    {qualificationLabel(q)}
                  </label>
                ))}
              </fieldset>
            )}
            {driverError && (
              <p role="alert" className="error">
                {driverError}
              </p>
            )}
            <button type="submit" disabled={isSavingDriver}>
              {isSavingDriver ? 'Saving…' : 'Add driver'}
            </button>
          </form>
        )}
      </section>

      <section>
        <h2>Vehicles</h2>
        <ul>
          {vehicles.map((v) => (
            <li key={v.id}>
              {v.label}
              {v.nominal_capacity != null && ` — capacity ${v.nominal_capacity}`}
              {v.qualifications.length > 0 &&
                ` (${v.qualifications.map((q) => q.code).join(', ')})`}
            </li>
          ))}
        </ul>
        {canCreate && (
          <form onSubmit={(event) => void handleCreateVehicle(event)}>
            <label htmlFor="vehicle-label">Label</label>
            <input
              id="vehicle-label"
              value={vehicleLabel}
              onChange={(event) => setVehicleLabel(event.target.value)}
              required
            />
            <label htmlFor="vehicle-nominal-capacity">Nominal capacity (optional)</label>
            <input
              id="vehicle-nominal-capacity"
              type="number"
              min="1"
              value={vehicleNominalCapacity}
              onChange={(event) => setVehicleNominalCapacity(event.target.value)}
            />
            <label htmlFor="vehicle-effective-capacity">Effective capacity (optional)</label>
            <input
              id="vehicle-effective-capacity"
              type="number"
              min="1"
              value={vehicleEffectiveCapacity}
              onChange={(event) => setVehicleEffectiveCapacity(event.target.value)}
            />
            {vehicleQualifications.length > 0 && (
              <fieldset>
                <legend>Vehicle capability qualifications</legend>
                {vehicleQualifications.map((q) => (
                  <label key={q.id} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={vehicleQualCodes.has(q.code)}
                      onChange={() => toggleVehicleQual(q.code)}
                    />
                    {qualificationLabel(q)}
                  </label>
                ))}
              </fieldset>
            )}
            {vehicleError && (
              <p role="alert" className="error">
                {vehicleError}
              </p>
            )}
            <button type="submit" disabled={isSavingVehicle}>
              {isSavingVehicle ? 'Saving…' : 'Add vehicle'}
            </button>
          </form>
        )}
      </section>
    </main>
  )
}
