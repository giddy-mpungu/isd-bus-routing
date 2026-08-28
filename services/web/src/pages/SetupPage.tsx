import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  Driver,
  Qualification,
  QualificationKind,
  RidershipDefault,
  School,
  Stop,
  Student,
  Vehicle,
} from '../api/types'
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
  const [stops, setStops] = useState<Stop[]>([])
  const [students, setStudents] = useState<Student[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const loadAll = useCallback(async () => {
    setErrorMessage(null)
    try {
      const [schoolsData, qualificationsData, driversData, vehiclesData, stopsData, studentsData] =
        await Promise.all([
          api.getSchools(),
          api.getQualifications(),
          api.getDrivers(),
          api.getVehicles(),
          api.getStops(),
          api.getStudents(),
        ])
      setSchools(schoolsData)
      setQualifications(qualificationsData)
      setDrivers(driversData)
      setVehicles(vehiclesData)
      setStops(stopsData)
      setStudents(studentsData)
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

  // --- Stops ---
  const [stopLabel, setStopLabel] = useState('')
  const [stopLat, setStopLat] = useState('')
  const [stopLon, setStopLon] = useState('')
  const [stopError, setStopError] = useState<string | null>(null)
  const [isSavingStop, setIsSavingStop] = useState(false)

  async function handleCreateStop(event: FormEvent) {
    event.preventDefault()
    setStopError(null)
    setIsSavingStop(true)
    try {
      await api.createStop({
        label: stopLabel,
        location_lat: Number(stopLat),
        location_lon: Number(stopLon),
      })
      setStopLabel('')
      setStopLat('')
      setStopLon('')
      await loadAll()
    } catch (err) {
      setStopError(err instanceof ApiError ? err.message : 'Failed to create stop.')
    } finally {
      setIsSavingStop(false)
    }
  }

  // --- Students ---
  const [studentName, setStudentName] = useState('')
  const [studentSchoolId, setStudentSchoolId] = useState('')
  const [studentStopId, setStudentStopId] = useState('')
  const [studentDefaultRidership, setStudentDefaultRidership] = useState<RidershipDefault>('rides')
  const [studentError, setStudentError] = useState<string | null>(null)
  const [isSavingStudent, setIsSavingStudent] = useState(false)

  async function handleCreateStudent(event: FormEvent) {
    event.preventDefault()
    setStudentError(null)
    setIsSavingStudent(true)
    try {
      await api.createStudent({
        full_name: studentName,
        school_id: Number(studentSchoolId),
        stop_id: studentStopId ? Number(studentStopId) : undefined,
        default_ridership: studentDefaultRidership,
      })
      setStudentName('')
      setStudentSchoolId('')
      setStudentStopId('')
      setStudentDefaultRidership('rides')
      await loadAll()
    } catch (err) {
      setStudentError(err instanceof ApiError ? err.message : 'Failed to create student.')
    } finally {
      setIsSavingStudent(false)
    }
  }

  const schoolsById = new Map(schools.map((s) => [s.id, s]))
  const stopsById = new Map(stops.map((s) => [s.id, s]))

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

      <section>
        <h2>Stops</h2>
        <ul>
          {stops.map((s) => (
            <li key={s.id}>
              {s.label} ({s.location_lat}, {s.location_lon})
            </li>
          ))}
        </ul>
        {canCreate && (
          <form onSubmit={(event) => void handleCreateStop(event)}>
            <label htmlFor="stop-label">Stop label</label>
            <input
              id="stop-label"
              value={stopLabel}
              onChange={(event) => setStopLabel(event.target.value)}
              required
            />
            <label htmlFor="stop-lat">Stop latitude</label>
            <input
              id="stop-lat"
              type="number"
              step="any"
              value={stopLat}
              onChange={(event) => setStopLat(event.target.value)}
              required
            />
            <label htmlFor="stop-lon">Stop longitude</label>
            <input
              id="stop-lon"
              type="number"
              step="any"
              value={stopLon}
              onChange={(event) => setStopLon(event.target.value)}
              required
            />
            {stopError && (
              <p role="alert" className="error">
                {stopError}
              </p>
            )}
            <button type="submit" disabled={isSavingStop}>
              {isSavingStop ? 'Saving…' : 'Add stop'}
            </button>
          </form>
        )}
      </section>

      <section>
        <h2>Students</h2>
        <ul>
          {students.map((s) => (
            <li key={s.id}>
              {s.full_name} — {schoolsById.get(s.school_id)?.name ?? `School ${s.school_id}`}
              {s.stop_id != null && ` (${stopsById.get(s.stop_id)?.label ?? `Stop ${s.stop_id}`})`}
              {' — default: '}
              {s.default_ridership === 'rides' ? 'rides' : 'does not ride'}
            </li>
          ))}
        </ul>
        {canCreate && (
          <form onSubmit={(event) => void handleCreateStudent(event)}>
            <label htmlFor="student-name">Student name</label>
            <input
              id="student-name"
              value={studentName}
              onChange={(event) => setStudentName(event.target.value)}
              required
            />
            <label htmlFor="student-school">School</label>
            <select
              id="student-school"
              value={studentSchoolId}
              onChange={(event) => setStudentSchoolId(event.target.value)}
              required
            >
              <option value="">Select a school</option>
              {schools.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <label htmlFor="student-stop">Stop (optional)</label>
            <select
              id="student-stop"
              value={studentStopId}
              onChange={(event) => setStudentStopId(event.target.value)}
            >
              <option value="">Not yet assigned</option>
              {stops.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
            <label htmlFor="student-default-ridership">Default ridership</label>
            <select
              id="student-default-ridership"
              value={studentDefaultRidership}
              onChange={(event) =>
                setStudentDefaultRidership(event.target.value as RidershipDefault)
              }
            >
              <option value="rides">Rides every school day</option>
              <option value="does_not_ride">Does not ride unless requested</option>
            </select>
            {studentError && (
              <p role="alert" className="error">
                {studentError}
              </p>
            )}
            <button type="submit" disabled={isSavingStudent}>
              {isSavingStudent ? 'Saving…' : 'Add student'}
            </button>
          </form>
        )}
      </section>
    </main>
  )
}
