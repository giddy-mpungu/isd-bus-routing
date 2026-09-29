import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
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
  RestrictedVehicleDimension,
  School,
  Stop,
  Student,
  Vehicle,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { TabList, TabPanel, type TabItem } from '../components/Tabs'
import { DriversSection } from './DriversSection'
import { OptimizationSettingsSection } from './OptimizationSettingsSection'
import { QualificationsSection } from './QualificationsSection'
import { RidershipRulesSection } from './RidershipRulesSection'
import { SchoolsSection } from './SchoolsSection'
import { SisImportSection } from './SisImportSection'
import { StopProposalsSection } from './StopProposalsSection'
import { StopsSection } from './StopsSection'
import { StudentsSection } from './StudentsSection'
import { TransportationRulesSection } from './TransportationRulesSection'
import { VehiclesSection } from './VehiclesSection'

// Creating a school/qualification/driver/vehicle is transportation_admin
// only (services/api/src/isd_api/routers/{schools,qualifications,drivers,
// vehicles}.py) — dispatcher can read all four lists but sees no create
// forms here, matching what the backend would reject anyway.

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

type SetupTab =
  | 'schools'
  | 'fleet'
  | 'district-knowledge'
  | 'announcements'
  | 'optimization'
  | 'sis-import'
  | 'audit-log'

// SIS import and the audit log are transportation_admin-only sections
// (see canCreate below), so their tabs only exist for that role.
const ADMIN_ONLY_TABS: SetupTab[] = ['sis-import', 'audit-log']

const TAB_PREFIX = 'setup'

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

  const schoolsById = new Map(schools.map((s) => [s.id, s]))

  // --- Tabs --- the active tab lives in the URL (?tab=fleet) so a
  // section is deep-linkable and survives a reload. An unknown or
  // role-inaccessible value falls back to the first tab rather than
  // rendering an empty page.
  const allTabs: (TabItem & { id: SetupTab })[] = [
    { id: 'schools', label: 'Schools & students' },
    { id: 'fleet', label: 'Fleet & drivers' },
    { id: 'district-knowledge', label: 'District knowledge', count: geoOverrides.length },
    { id: 'announcements', label: 'Announcements', count: announcements.length },
    { id: 'optimization', label: 'Rules & optimization' },
    { id: 'sis-import', label: 'SIS import' },
    { id: 'audit-log', label: 'Audit log' },
  ]
  const tabs = allTabs.filter((t) => canCreate || !ADMIN_ONLY_TABS.includes(t.id))
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const activeTab: SetupTab = tabs.find((t) => t.id === requestedTab)?.id ?? 'schools'

  function selectTab(id: string) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('tab', id)
        return next
      },
      { replace: true },
    )
  }

  // At-a-glance totals across the page; each tile jumps to the tab that
  // manages that record type.
  const stats: { label: string; value: number; tab: SetupTab }[] = [
    { label: 'Schools', value: schools.length, tab: 'schools' },
    { label: 'Students', value: students.length, tab: 'schools' },
    { label: 'Stops', value: stops.length, tab: 'schools' },
    { label: 'Active drivers', value: drivers.filter((d) => d.is_active).length, tab: 'fleet' },
    { label: 'Active vehicles', value: vehicles.filter((v) => v.is_active).length, tab: 'fleet' },
  ]

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
      <h1>Setup</h1>
      <p>
        The district's master data and configuration — schools, fleet, drivers, stops, and the
        knowledge and settings the scheduler plans with.
      </p>
      {errorMessage && (
        <p role="alert" className="error">
          {errorMessage}
        </p>
      )}

      <div className="setup-stats">
        {stats.map((s) => (
          <button
            key={s.label}
            type="button"
            className="setup-stat"
            // The two spans stack visually with no text between them, so
            // spell the name out rather than leave it as "1Schools".
            aria-label={`${s.value} ${s.label}`}
            onClick={() => selectTab(s.tab)}
          >
            <span className="setup-stat-value">{s.value}</span>
            <span className="setup-stat-label">{s.label}</span>
          </button>
        ))}
      </div>

      <TabList
        items={tabs}
        activeId={activeTab}
        onSelect={selectTab}
        idPrefix={TAB_PREFIX}
        label="Setup sections"
      />

      <TabPanel id="schools" activeId={activeTab} idPrefix={TAB_PREFIX}>
        <SchoolsSection schools={schools} canEdit={canCreate} onChanged={loadAll} />

        <StopsSection stops={stops} students={students} canEdit={canCreate} onChanged={loadAll} />

        <StudentsSection
          students={students}
          schools={schools}
          stops={stops}
          qualifications={qualifications}
          canEdit={canCreate}
          onChanged={loadAll}
        />

        {canCreate && <StopProposalsSection schools={schools} stops={stops} onChanged={loadAll} />}
      </TabPanel>

      <TabPanel id="fleet" activeId={activeTab} idPrefix={TAB_PREFIX}>
        <QualificationsSection
          qualifications={qualifications}
          canEdit={canCreate}
          onChanged={loadAll}
        />

        <DriversSection
          drivers={drivers}
          qualifications={qualifications}
          canEdit={canCreate}
          onChanged={loadAll}
        />

        <VehiclesSection
          vehicles={vehicles}
          qualifications={qualifications}
          canEdit={canCreate}
          onChanged={loadAll}
        />
      </TabPanel>

      <TabPanel id="district-knowledge" activeId={activeTab} idPrefix={TAB_PREFIX}>
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
      </TabPanel>

      <TabPanel id="announcements" activeId={activeTab} idPrefix={TAB_PREFIX}>
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
      </TabPanel>

      <TabPanel id="optimization" activeId={activeTab} idPrefix={TAB_PREFIX}>
        <TransportationRulesSection canEdit={canCreate} />
        <RidershipRulesSection canEdit={canCreate} />
        <OptimizationSettingsSection canEdit={canCreate} />
      </TabPanel>

      {canCreate && (
        <TabPanel id="sis-import" activeId={activeTab} idPrefix={TAB_PREFIX}>
          <SisImportSection schools={schools} onSchoolsChanged={loadAll} />
        </TabPanel>
      )}

      {canCreate && (
        <TabPanel id="audit-log" activeId={activeTab} idPrefix={TAB_PREFIX}>
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
        </TabPanel>
      )}
    </main>
  )
}
