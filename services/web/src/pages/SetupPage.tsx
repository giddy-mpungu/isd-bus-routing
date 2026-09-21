import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  Announcement,
  AnnouncementAudience,
  AnnouncementCategory,
  AuditLogEntry,
  Driver,
  GeographicKnowledgeCategory,
  GeographicKnowledgeOverride,
  Qualification,
  QualificationKind,
  RestrictedVehicleDimension,
  RidershipDefault,
  School,
  Stop,
  Student,
  Vehicle,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { OptimizationSettingsSection } from './OptimizationSettingsSection'

// Creating a school/qualification/driver/vehicle is transportation_admin
// only (services/api/src/isd_api/routers/{schools,qualifications,drivers,
// vehicles}.py) — dispatcher can read all four lists but sees no create
// forms here, matching what the backend would reject anyway.

function qualificationLabel(q: Qualification): string {
  return q.description ? `${q.code} — ${q.description}` : q.code
}

const GEO_CATEGORIES: GeographicKnowledgeCategory[] = [
  'frequent_flooding',
  'difficult_intersection',
  'unsafe_turn',
  'invalid_turnaround',
  'congestion_window',
  'vehicle_size_restricted',
  'preferred_entrance',
  'other',
]

const ANNOUNCEMENT_CATEGORIES: AnnouncementCategory[] = [
  'general',
  'delay',
  'substitution',
  'route_change',
]
const ANNOUNCEMENT_AUDIENCES: AnnouncementAudience[] = ['all', 'family', 'driver']

export function SetupPage() {
  const { user } = useAuth()
  const canCreate = user?.role === 'transportation_admin'
  // District geographic-knowledge overrides are day-to-day operational
  // knowledge (services/api/src/isd_api/routers/geographic_knowledge.py
  // allows both roles to create), not structural master data like
  // schools/vehicles — so this section's create form has its own,
  // broader gate than canCreate above.
  const canCreateDistrictKnowledge =
    user?.role === 'transportation_admin' || user?.role === 'dispatcher'
  // Same RBAC as canCreateDistrictKnowledge (services/api/src/isd_api/
  // routers/announcements.py's _WRITE_ROLES) -- day-to-day operational
  // communication, not structural master data.
  const canCreateAnnouncement = canCreateDistrictKnowledge

  const [schools, setSchools] = useState<School[]>([])
  const [qualifications, setQualifications] = useState<Qualification[]>([])
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [stops, setStops] = useState<Stop[]>([])
  const [students, setStudents] = useState<Student[]>([])
  const [geoOverrides, setGeoOverrides] = useState<GeographicKnowledgeOverride[]>([])
  const [announcements, setAnnouncements] = useState<Announcement[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const loadAll = useCallback(async () => {
    setErrorMessage(null)
    try {
      const [
        schoolsData,
        qualificationsData,
        driversData,
        vehiclesData,
        stopsData,
        studentsData,
        geoOverridesData,
        announcementsData,
      ] = await Promise.all([
        api.getSchools(),
        api.getQualifications(),
        api.getDrivers(),
        api.getVehicles(),
        api.getStops(),
        api.getStudents(),
        api.getGeographicKnowledgeOverrides(),
        api.getAnnouncements(),
      ])
      setSchools(schoolsData)
      setQualifications(qualificationsData)
      setDrivers(driversData)
      setVehicles(vehiclesData)
      setStops(stopsData)
      setStudents(studentsData)
      setGeoOverrides(geoOverridesData)
      setAnnouncements(announcementsData)
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
  const [vehicleLength, setVehicleLength] = useState('')
  const [vehicleWidth, setVehicleWidth] = useState('')
  const [vehicleHeight, setVehicleHeight] = useState('')
  const [vehicleWeight, setVehicleWeight] = useState('')
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
        length_m: vehicleLength ? Number(vehicleLength) : undefined,
        width_m: vehicleWidth ? Number(vehicleWidth) : undefined,
        height_m: vehicleHeight ? Number(vehicleHeight) : undefined,
        weight_kg: vehicleWeight ? Number(vehicleWeight) : undefined,
        qualification_codes: Array.from(vehicleQualCodes),
      })
      setVehicleLabel('')
      setVehicleNominalCapacity('')
      setVehicleEffectiveCapacity('')
      setVehicleLength('')
      setVehicleWidth('')
      setVehicleHeight('')
      setVehicleWeight('')
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

  // --- District geographic knowledge (spec section 8) ---
  const [geoLat, setGeoLat] = useState('')
  const [geoLon, setGeoLon] = useState('')
  const [geoCategory, setGeoCategory] = useState<GeographicKnowledgeCategory>('frequent_flooding')
  const [geoNote, setGeoNote] = useState('')
  // Only meaningful for category=congestion_window (routers/
  // geographic_knowledge.py rejects them for every other category).
  const [geoWindowStart, setGeoWindowStart] = useState('')
  const [geoWindowEnd, setGeoWindowEnd] = useState('')
  // Only meaningful for category=vehicle_size_restricted.
  const [geoRestrictedDimension, setGeoRestrictedDimension] =
    useState<RestrictedVehicleDimension>('height_m')
  const [geoMaxAllowedValue, setGeoMaxAllowedValue] = useState('')
  // Only meaningful for category=preferred_entrance.
  const [geoSchoolId, setGeoSchoolId] = useState('')
  const [geoError, setGeoError] = useState<string | null>(null)
  const [isSavingGeo, setIsSavingGeo] = useState(false)

  async function handleCreateGeoOverride(event: FormEvent) {
    event.preventDefault()
    setGeoError(null)
    setIsSavingGeo(true)
    try {
      await api.createGeographicKnowledgeOverride({
        location_lat: Number(geoLat),
        location_lon: Number(geoLon),
        category: geoCategory,
        note: geoNote,
        window_start_minute: geoCategory === 'congestion_window' ? Number(geoWindowStart) : null,
        window_end_minute: geoCategory === 'congestion_window' ? Number(geoWindowEnd) : null,
        restricted_dimension:
          geoCategory === 'vehicle_size_restricted' ? geoRestrictedDimension : null,
        max_allowed_value:
          geoCategory === 'vehicle_size_restricted' ? Number(geoMaxAllowedValue) : null,
        school_id: geoCategory === 'preferred_entrance' ? Number(geoSchoolId) : null,
      })
      setGeoLat('')
      setGeoLon('')
      setGeoCategory('frequent_flooding')
      setGeoNote('')
      setGeoWindowStart('')
      setGeoWindowEnd('')
      setGeoRestrictedDimension('height_m')
      setGeoMaxAllowedValue('')
      setGeoSchoolId('')
      await loadAll()
    } catch (err) {
      setGeoError(err instanceof ApiError ? err.message : 'Failed to create override.')
    } finally {
      setIsSavingGeo(false)
    }
  }

  // --- Announcements (spec section 9/18) ---
  const [announcementMessage, setAnnouncementMessage] = useState('')
  const [announcementCategory, setAnnouncementCategory] = useState<AnnouncementCategory>('general')
  const [announcementAudience, setAnnouncementAudience] = useState<AnnouncementAudience>('all')
  const [announcementSchoolId, setAnnouncementSchoolId] = useState('')
  const [announcementError, setAnnouncementError] = useState<string | null>(null)
  const [isSavingAnnouncement, setIsSavingAnnouncement] = useState(false)

  async function handleCreateAnnouncement(event: FormEvent) {
    event.preventDefault()
    setAnnouncementError(null)
    setIsSavingAnnouncement(true)
    try {
      await api.createAnnouncement({
        message: announcementMessage,
        category: announcementCategory,
        audience: announcementAudience,
        school_id: announcementSchoolId ? Number(announcementSchoolId) : null,
      })
      setAnnouncementMessage('')
      setAnnouncementCategory('general')
      setAnnouncementAudience('all')
      setAnnouncementSchoolId('')
      await loadAll()
    } catch (err) {
      setAnnouncementError(err instanceof ApiError ? err.message : 'Failed to post announcement.')
    } finally {
      setIsSavingAnnouncement(false)
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

  // --- Audit log (spec section 17/21) --- transportation_admin only,
  // loaded on demand rather than as part of loadAll(), since a
  // dispatcher visiting this page would otherwise trigger a pointless
  // 403 on every load.
  const [auditEntityTypes, setAuditEntityTypes] = useState<string[]>([])
  const [auditEntityTypeFilter, setAuditEntityTypeFilter] = useState('')
  const [auditEntityIdFilter, setAuditEntityIdFilter] = useState('')
  const [auditEntries, setAuditEntries] = useState<AuditLogEntry[]>([])
  const [auditError, setAuditError] = useState<string | null>(null)
  const [isLoadingAudit, setIsLoadingAudit] = useState(false)
  const [hasLoadedAudit, setHasLoadedAudit] = useState(false)
  const auditPageSize = 20

  async function loadAuditLog(offset: number) {
    setAuditError(null)
    setIsLoadingAudit(true)
    try {
      if (auditEntityTypes.length === 0) {
        setAuditEntityTypes(await api.getAuditLogEntityTypes())
      }
      const entries = await api.getAuditLog({
        entity_type: auditEntityTypeFilter || undefined,
        entity_id: auditEntityIdFilter ? Number(auditEntityIdFilter) : undefined,
        limit: auditPageSize,
        offset,
      })
      setAuditEntries(offset === 0 ? entries : [...auditEntries, ...entries])
      setHasLoadedAudit(true)
    } catch (err) {
      setAuditError(err instanceof ApiError ? err.message : 'Failed to load the audit log.')
    } finally {
      setIsLoadingAudit(false)
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
              {(v.length_m != null || v.width_m != null || v.height_m != null) &&
                ` — ${v.length_m ?? '?'}m × ${v.width_m ?? '?'}m × ${v.height_m ?? '?'}m`}
              {v.weight_kg != null && ` — ${v.weight_kg}kg`}
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
            <label htmlFor="vehicle-length">Length in meters (optional)</label>
            <input
              id="vehicle-length"
              type="number"
              step="any"
              min="0.01"
              value={vehicleLength}
              onChange={(event) => setVehicleLength(event.target.value)}
            />
            <label htmlFor="vehicle-width">Width in meters (optional)</label>
            <input
              id="vehicle-width"
              type="number"
              step="any"
              min="0.01"
              value={vehicleWidth}
              onChange={(event) => setVehicleWidth(event.target.value)}
            />
            <label htmlFor="vehicle-height">Height in meters (optional)</label>
            <input
              id="vehicle-height"
              type="number"
              step="any"
              min="0.01"
              value={vehicleHeight}
              onChange={(event) => setVehicleHeight(event.target.value)}
            />
            <label htmlFor="vehicle-weight">Weight in kg (optional)</label>
            <input
              id="vehicle-weight"
              type="number"
              step="any"
              min="0.01"
              value={vehicleWeight}
              onChange={(event) => setVehicleWeight(event.target.value)}
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
        <h2>District geographic knowledge</h2>
        <ul>
          {geoOverrides.map((o) => (
            <li key={o.id}>
              [{o.category.replace(/_/g, ' ')}] {o.note} ({o.location_lat}, {o.location_lon})
              {o.window_start_minute != null &&
                ` — ${o.window_start_minute}-${o.window_end_minute} min`}
              {o.restricted_dimension != null &&
                ` — max ${o.restricted_dimension.replace(/_/g, ' ')} ${o.max_allowed_value}`}
              {o.school_id != null &&
                ` — ${schoolsById.get(o.school_id)?.name ?? `School ${o.school_id}`}`}
            </li>
          ))}
        </ul>
        {canCreateDistrictKnowledge && (
          <form onSubmit={(event) => void handleCreateGeoOverride(event)}>
            <label htmlFor="geo-lat">Override latitude</label>
            <input
              id="geo-lat"
              type="number"
              step="any"
              value={geoLat}
              onChange={(event) => setGeoLat(event.target.value)}
              required
            />
            <label htmlFor="geo-lon">Override longitude</label>
            <input
              id="geo-lon"
              type="number"
              step="any"
              value={geoLon}
              onChange={(event) => setGeoLon(event.target.value)}
              required
            />
            <label htmlFor="geo-category">Category</label>
            <select
              id="geo-category"
              value={geoCategory}
              onChange={(event) =>
                setGeoCategory(event.target.value as GeographicKnowledgeCategory)
              }
            >
              {GEO_CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {category.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            {geoCategory === 'congestion_window' && (
              <>
                <label htmlFor="geo-window-start">Congestion window start (minute of day)</label>
                <input
                  id="geo-window-start"
                  type="number"
                  value={geoWindowStart}
                  onChange={(event) => setGeoWindowStart(event.target.value)}
                  required
                />
                <label htmlFor="geo-window-end">Congestion window end (minute of day)</label>
                <input
                  id="geo-window-end"
                  type="number"
                  value={geoWindowEnd}
                  onChange={(event) => setGeoWindowEnd(event.target.value)}
                  required
                />
              </>
            )}
            {geoCategory === 'vehicle_size_restricted' && (
              <>
                <label htmlFor="geo-restricted-dimension">Restricted dimension</label>
                <select
                  id="geo-restricted-dimension"
                  value={geoRestrictedDimension}
                  onChange={(event) =>
                    setGeoRestrictedDimension(event.target.value as RestrictedVehicleDimension)
                  }
                >
                  <option value="length_m">length</option>
                  <option value="width_m">width</option>
                  <option value="height_m">height</option>
                  <option value="weight_kg">weight</option>
                </select>
                <label htmlFor="geo-max-allowed">Max allowed value</label>
                <input
                  id="geo-max-allowed"
                  type="number"
                  step="any"
                  value={geoMaxAllowedValue}
                  onChange={(event) => setGeoMaxAllowedValue(event.target.value)}
                  required
                />
              </>
            )}
            {geoCategory === 'preferred_entrance' && (
              <>
                <label htmlFor="geo-school">School</label>
                <select
                  id="geo-school"
                  value={geoSchoolId}
                  onChange={(event) => setGeoSchoolId(event.target.value)}
                  required
                >
                  <option value="">Select a school</option>
                  {schools.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </>
            )}
            <label htmlFor="geo-note">Note</label>
            <textarea
              id="geo-note"
              value={geoNote}
              onChange={(event) => setGeoNote(event.target.value)}
              required
            />
            {geoError && (
              <p role="alert" className="error">
                {geoError}
              </p>
            )}
            <button type="submit" disabled={isSavingGeo}>
              {isSavingGeo ? 'Saving…' : 'Add override'}
            </button>
          </form>
        )}
      </section>

      <section>
        <h2>Announcements</h2>
        <ul>
          {announcements.map((a) => (
            <li key={a.id}>
              [{a.category.replace(/_/g, ' ')} — {a.audience}
              {a.school_id != null &&
                ` — ${schoolsById.get(a.school_id)?.name ?? `School ${a.school_id}`}`}
              ] {a.message}
            </li>
          ))}
        </ul>
        {canCreateAnnouncement && (
          <form onSubmit={(event) => void handleCreateAnnouncement(event)}>
            <label htmlFor="announcement-message">Message</label>
            <textarea
              id="announcement-message"
              value={announcementMessage}
              onChange={(event) => setAnnouncementMessage(event.target.value)}
              required
            />
            <label htmlFor="announcement-category">Announcement category</label>
            <select
              id="announcement-category"
              value={announcementCategory}
              onChange={(event) =>
                setAnnouncementCategory(event.target.value as AnnouncementCategory)
              }
            >
              {ANNOUNCEMENT_CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {category.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            <label htmlFor="announcement-audience">Audience</label>
            <select
              id="announcement-audience"
              value={announcementAudience}
              onChange={(event) =>
                setAnnouncementAudience(event.target.value as AnnouncementAudience)
              }
            >
              {ANNOUNCEMENT_AUDIENCES.map((audience) => (
                <option key={audience} value={audience}>
                  {audience}
                </option>
              ))}
            </select>
            <label htmlFor="announcement-school">
              School (optional — leave blank for district-wide)
            </label>
            <select
              id="announcement-school"
              value={announcementSchoolId}
              onChange={(event) => setAnnouncementSchoolId(event.target.value)}
            >
              <option value="">District-wide</option>
              {schools.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {announcementError && (
              <p role="alert" className="error">
                {announcementError}
              </p>
            )}
            <button type="submit" disabled={isSavingAnnouncement}>
              {isSavingAnnouncement ? 'Posting…' : 'Post announcement'}
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

      <OptimizationSettingsSection canEdit={canCreate} />

      {canCreate && (
        <section>
          <h2>Audit log</h2>
          <div className="audit-log-filters">
            <label htmlFor="audit-entity-type">Entity type</label>
            <select
              id="audit-entity-type"
              value={auditEntityTypeFilter}
              onChange={(event) => setAuditEntityTypeFilter(event.target.value)}
            >
              <option value="">All</option>
              {auditEntityTypes.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            <label htmlFor="audit-entity-id">Entity ID (optional)</label>
            <input
              id="audit-entity-id"
              type="number"
              value={auditEntityIdFilter}
              onChange={(event) => setAuditEntityIdFilter(event.target.value)}
            />
            <button type="button" disabled={isLoadingAudit} onClick={() => void loadAuditLog(0)}>
              {isLoadingAudit ? 'Loading…' : hasLoadedAudit ? 'Refresh' : 'Load audit log'}
            </button>
          </div>
          {auditError && (
            <p role="alert" className="error">
              {auditError}
            </p>
          )}
          {hasLoadedAudit && auditEntries.length === 0 && !auditError && (
            <p className="status">No matching audit log entries.</p>
          )}
          <ul className="audit-log-list">
            {auditEntries.map((entry) => (
              <li key={entry.id} className="audit-log-entry">
                <div className="audit-log-entry-head">
                  <span className="mono">{entry.created_at}</span>
                  {' — '}
                  <b>{entry.actor_full_name ?? 'system'}</b>
                  {' — '}
                  {entry.action} {entry.entity_type.replace(/_/g, ' ')} #{entry.entity_id}
                </div>
                {entry.after_state && (
                  <pre className="audit-log-state">{JSON.stringify(entry.after_state)}</pre>
                )}
              </li>
            ))}
          </ul>
          {hasLoadedAudit &&
            auditEntries.length > 0 &&
            auditEntries.length % auditPageSize === 0 && (
              <button
                type="button"
                disabled={isLoadingAudit}
                onClick={() => void loadAuditLog(auditEntries.length)}
              >
                {isLoadingAudit ? 'Loading…' : 'Load more'}
              </button>
            )}
        </section>
      )}
    </main>
  )
}
