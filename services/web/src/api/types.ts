// Mirrors services/api/src/isd_api/schemas.py and models.py Role enum
// (spec section 17). Kept hand-written rather than generated — the
// endpoint surface this console uses is still small (see client.ts).

export type Role =
  'driver' | 'student' | 'parent' | 'school_admin' | 'dispatcher' | 'transportation_admin'

export interface CurrentUser {
  id: number
  email: string
  full_name: string
  role: Role
  is_active: boolean
  driver_id: number | null
  school_id: number | null
  student_id: number | null
}

export interface User extends CurrentUser {
  created_at: string
}

export interface UserCreate {
  email: string
  password: string
  full_name: string
  role: Role
  driver_id?: number
  school_id?: number
  student_id?: number
}

export interface UserUpdate {
  role?: Role
  is_active?: boolean
  driver_id?: number
  school_id?: number
  student_id?: number
}

export interface School {
  id: number
  name: string
  location_lat: number
  location_lon: number
  // The SIS's identifier for this school; roster rows can only be placed
  // at a school that has one.
  external_id?: string | null
}

export type QualificationKind = 'license' | 'vehicle_capability'

export interface Qualification {
  id: number
  code: string
  kind: QualificationKind
  description: string | null
  is_active: boolean
}

// Spec section 15: tiered CDL A > CDL B > Class C (non-CDL). A driver may
// drive any vehicle whose required class is at or below their own.
export type LicenseClass = 'cdl_a' | 'cdl_b' | 'class_c'

export interface Driver {
  id: number
  full_name: string
  max_continuous_minutes: number | null
  // null = not on record, which qualifies for no vehicle.
  license_class: LicenseClass | null
  is_active: boolean
  qualifications: Qualification[]
}

export interface Vehicle {
  id: number
  label: string
  nominal_capacity: number | null
  effective_capacity: number | null
  length_m: number | null
  width_m: number | null
  height_m: number | null
  weight_kg: number | null
  required_license_class: LicenseClass
  is_active: boolean
  qualifications: Qualification[]
}

export interface Run {
  id: number
  service_date: string
  school_id: number
  direction: RideDirection
  window_earliest: number
  window_latest: number
  duration_minutes: number
  buffer_minutes: number
  passenger_count: number
}

export interface Crew {
  id: number
  service_date: string
  driver_id: number
  vehicle_id: number
  available_window_earliest: number
  available_window_latest: number
}

export interface Assignment {
  id: number
  run_id: number
  crew_id: number
  start_minute: number
  end_minute: number
  explanation_text: string
  locked: boolean
  status: AssignmentStatus
  // Set when the crew became unavailable after this assignment was made
  // (driver absent or deactivated, vehicle out of service).
  availability_issue: string | null
}

export interface ScheduleResult {
  crews_used: number
  assignments: Assignment[]
  total_deadhead_minutes: number | null
  total_arrival_buffer_minutes: number | null
}

export interface OptimizationSettingsUpdate {
  crews_used_weight: number
  deadhead_minutes_weight: number
  arrival_buffer_weight: number
  // Spec section 16: a hard floor on spare minutes between consecutive
  // runs on one crew, after travel. 0 = none.
  minimum_buffer_minutes: number
}

// Spec section 4.4: district ridership reporting rules.
export interface RidershipRulesUpdate {
  timezone: string
  am_cutoff_minute: number | null
  pm_cutoff_minute: number | null
}

export interface RidershipRules extends RidershipRulesUpdate {
  is_default: boolean
}

export interface OptimizationSettings extends OptimizationSettingsUpdate {
  is_default: boolean
}

export interface AssignmentPatch {
  crew_id?: number
  start_minute?: number
  end_minute?: number
  locked?: boolean
}

// Spec section 14: Sent -> Received -> Acknowledged -> En Route -> Arrived
// -> In Progress -> Completed, plus No-show.
export type AssignmentStatus =
  | 'sent'
  | 'received'
  | 'acknowledged'
  | 'en_route'
  | 'arrived'
  | 'in_progress'
  | 'completed'
  | 'no_show'

export interface AssignmentStopRoster {
  stop_label: string | null
  student_names: string[]
}

export interface DriverAssignment {
  id: number
  run_id: number
  service_date: string
  school_name: string
  vehicle_label: string
  start_minute: number
  end_minute: number
  status: AssignmentStatus
  locked: boolean
  roster_ambiguous: boolean
  stops: AssignmentStopRoster[]
}

export interface SchoolAssignment {
  id: number
  run_id: number
  service_date: string
  direction: RideDirection
  window_earliest: number
  window_latest: number
  driver_full_name: string
  vehicle_label: string
  start_minute: number
  end_minute: number
  status: AssignmentStatus
  locked: boolean
}

export interface SchoolUpdate {
  name?: string
  location_lat?: number
  location_lon?: number
  external_id?: string | null
}

export interface SchoolCreate {
  name: string
  location_lat: number
  location_lon: number
}

export interface QualificationCreate {
  code: string
  kind: QualificationKind
  description?: string
}

export interface QualificationUpdate {
  description?: string
  is_active?: boolean
}

export interface DriverCreate {
  full_name: string
  max_continuous_minutes?: number
  qualification_codes: string[]
  license_class?: LicenseClass
}

export interface DriverUpdate {
  full_name?: string
  max_continuous_minutes?: number
  qualification_codes?: string[]
  is_active?: boolean
  license_class?: LicenseClass | null
}

export interface VehicleCreate {
  label: string
  nominal_capacity?: number
  effective_capacity?: number
  length_m?: number
  width_m?: number
  height_m?: number
  weight_kg?: number
  qualification_codes: string[]
  // Omitted = inferred from capacity (15+ passengers needs CDL B).
  required_license_class?: LicenseClass
}

export interface VehicleUpdate {
  label?: string
  nominal_capacity?: number
  effective_capacity?: number
  length_m?: number
  width_m?: number
  height_m?: number
  weight_kg?: number
  qualification_codes?: string[]
  is_active?: boolean
  required_license_class?: LicenseClass
}

export interface CrewCreate {
  service_date: string
  driver_id: number
  vehicle_id: number
  available_window_earliest: number
  available_window_latest: number
}

export interface RunCreate {
  service_date: string
  school_id: number
  direction: RideDirection
  window_earliest: number
  window_latest: number
  duration_minutes: number
  buffer_minutes: number
  passenger_count: number
  required_qualification_codes: string[]
}

export interface RunUpdate {
  passenger_count?: number
}

export interface ExpectedRiders {
  expected_passenger_count: number
  ambiguous: boolean
  riding_student_names: string[]
}

// spec §20: historical learning applied to Run.duration_minutes.
export interface ObservedRunDuration {
  sample_count: number
  average_actual_minutes: number | null
  most_recent_actual_minutes: number | null
  most_recent_service_date: string | null
}

export interface Stop {
  id: number
  label: string
  location_lat: number
  location_lon: number
}

export interface StopUpdate {
  label?: string
  location_lat?: number
  location_lon?: number
}

export interface StopCreate {
  label: string
  location_lat: number
  location_lon: number
}

export type RidershipDefault = 'rides' | 'does_not_ride'

export interface Student {
  id: number
  full_name: string
  school_id: number
  stop_id: number | null
  default_ridership: RidershipDefault
  // Set for students imported from the SIS: their name and school are
  // owned by the SIS and can't be edited here.
  external_id?: string | null
}

// Only the fields sent are changed; stop_id: null clears the stop.
export interface StudentUpdate {
  full_name?: string
  school_id?: number
  stop_id?: number | null
  default_ridership?: RidershipDefault
}

export interface Guardian {
  user_id: number
  full_name: string
  email: string
}

export interface StudentCreate {
  full_name: string
  school_id: number
  stop_id?: number
  default_ridership: RidershipDefault
}

export type RideDirection = 'am' | 'pm'

export interface RidershipOverrideUpdate {
  service_date: string
  direction: RideDirection
  is_riding: boolean
}

export interface FamilyMember {
  student_id: number
  full_name: string
  school_name: string
  stop_label: string | null
  service_date: string
  riding_am: boolean
  riding_pm: boolean
  // Set when the family can no longer change that leg (a past day, or
  // today after the district's cutoff), with the reason to show.
  am_changes_closed: string | null
  pm_changes_closed: string | null
}

export type AbsenceReason =
  | 'sick_leave'
  | 'personal_day'
  | 'vacation'
  | 'emergency_leave'
  | 'training'
  | 'approved_leave'
  | 'administrative_direction'
  | 'injury'
  | 'no_call_no_show'
  | 'other'

export interface Absence {
  id: number
  driver_id: number
  service_date: string
  start_minute: number
  end_minute: number
  reason: AbsenceReason
}

export interface AbsenceCreate {
  service_date: string
  start_minute: number
  end_minute: number
  reason: AbsenceReason
}

export interface SubstituteCandidate {
  driver_id: number
  full_name: string
  score: number
  reasons: string[]
}

export interface AffectedAssignmentSubstitutes {
  assignment_id: number
  run_id: number
  school_name: string
  start_minute: number
  end_minute: number
  crew_id: number
  vehicle_id: number
  vehicle_label: string
  candidates: SubstituteCandidate[]
}

export type GeographicKnowledgeCategory =
  | 'frequent_flooding'
  | 'difficult_intersection'
  | 'unsafe_turn'
  | 'invalid_turnaround'
  | 'congestion_window'
  | 'vehicle_size_restricted'
  | 'preferred_entrance'
  | 'other'

// Matches Vehicle's own length_m/width_m/height_m/weight_kg field
// names exactly (services/api's RestrictedVehicleDimension does a
// plain getattr against them).
export type RestrictedVehicleDimension = 'length_m' | 'width_m' | 'height_m' | 'weight_kg'

export interface GeographicKnowledgeOverride {
  id: number
  location_lat: number
  location_lon: number
  category: GeographicKnowledgeCategory
  note: string
  // Required together, and only meaningful, for category=congestion_window.
  window_start_minute: number | null
  window_end_minute: number | null
  // Required together, and only meaningful, for category=vehicle_size_restricted.
  restricted_dimension: RestrictedVehicleDimension | null
  max_allowed_value: number | null
  // Required, and only meaningful, for category=preferred_entrance --
  // this override's own location_lat/location_lon becomes that
  // school's regular runs' job location, instead of the school's own.
  school_id: number | null
  created_at: string
}

export interface GeographicKnowledgeOverrideCreate {
  location_lat: number
  location_lon: number
  category: GeographicKnowledgeCategory
  note: string
  window_start_minute?: number | null
  window_end_minute?: number | null
  restricted_dimension?: RestrictedVehicleDimension | null
  max_allowed_value?: number | null
  school_id?: number | null
}

// spec §9/§18: dispatcher-authored notices for drivers and/or families.
export type AnnouncementAudience = 'all' | 'family' | 'driver'
export type AnnouncementCategory = 'general' | 'delay' | 'substitution' | 'route_change'

export interface Announcement {
  id: number
  message: string
  category: AnnouncementCategory
  audience: AnnouncementAudience
  school_id: number | null
  created_at: string
}

export interface AnnouncementCreate {
  message: string
  category?: AnnouncementCategory
  audience: AnnouncementAudience
  school_id?: number | null
}

// spec §9: driver-app incident reporting / vehicle defect reporting.
export type DriverReportType = 'incident' | 'vehicle_defect'

export interface DriverReport {
  id: number
  driver_id: number
  vehicle_id: number | null
  service_date: string
  report_type: DriverReportType
  description: string
  created_at: string
}

export interface DriverReportCreate {
  service_date: string
  report_type: DriverReportType
  description: string
}

// ADR 0009: GPS telemetry pipeline.
export interface PositionUpdate {
  service_date: string
  location_lat: number
  location_lon: number
  recorded_at: string
}

export interface VehiclePosition {
  crew_id: number
  driver_id: number
  driver_full_name: string
  vehicle_id: number
  vehicle_label: string
  location_lat: number
  location_lon: number
  recorded_at: string
}

export interface BusPosition {
  available: boolean
  ambiguous: boolean
  location_lat: number | null
  location_lon: number | null
  recorded_at: string | null
  // No driver identity here, by design (spec section 18); the coordinates
  // are rounded server-side to roughly 100 m.
  vehicle_label: string | null
}

// spec §12: field trips (backend-only precursor was PR #25).
export type TripStatus =
  'requested' | 'approved' | 'assigned' | 'dispatched' | 'in_progress' | 'returning' | 'completed'

export interface DestinationProfile {
  id: number
  name: string
  location_lat: number | null
  location_lon: number | null
  approved_entrance: string | null
  parking_notes: string | null
  turn_restrictions: string | null
  driver_notes: string | null
  created_at: string
}

export interface DestinationProfileCreate {
  name: string
  location_lat?: number
  location_lon?: number
  approved_entrance?: string
  parking_notes?: string
  turn_restrictions?: string
  driver_notes?: string
}

export interface FieldTrip {
  id: number
  requesting_party: string
  origin: string
  destination: string
  destination_profile_id: number | null
  destination_profile: DestinationProfile | null
  departure_at: string
  expected_return_at: string
  actual_return_at: string | null
  passenger_count: number
  assigned_driver_id: number | null
  assigned_vehicle_id: number | null
  bus_assistant_name: string | null
  trip_contact: string
  special_instructions: string | null
  status: TripStatus
  required_qualifications: Qualification[]
}

export interface FieldTripCreate {
  requesting_party: string
  origin: string
  destination: string
  destination_profile_id?: number
  departure_at: string
  expected_return_at: string
  passenger_count: number
  trip_contact: string
  bus_assistant_name?: string
  special_instructions?: string
  required_qualification_codes: string[]
}

export interface FieldTripUpdate {
  status?: TripStatus
  assigned_driver_id?: number
  assigned_vehicle_id?: number
  destination_profile_id?: number
  expected_return_at?: string
  actual_return_at?: string
}

export interface FieldTripConflictCheck {
  conflicts: string[]
  // Regular routes the trip takes the driver or bus away from. They don't
  // block assignment; each is flagged "Needs cover" on the schedule.
  routes_needing_cover: string[]
  // Minutes held before departure and after return (pre/post-trip).
  turnaround_minutes: number
}

export interface FieldTripObservedDuration {
  sample_count: number
  average_actual_minutes: number | null
  most_recent_actual_minutes: number | null
  most_recent_departure_date: string | null
}

// spec §17/§21: the audit trail made readable. transportation_admin only.
export interface AuditLogEntry {
  id: number
  entity_type: string
  entity_id: number
  action: string
  actor_user_id: number | null
  actor_full_name: string | null
  before_state: Record<string, unknown> | null
  after_state: Record<string, unknown> | null
  created_at: string
}

export interface AuditLogQuery {
  entity_type?: string
  entity_id?: number
  limit?: number
  offset?: number
}

export interface RouteTemplate {
  id: number
  school_id: number
  direction: RideDirection
  window_earliest: number
  window_latest: number
  duration_minutes: number
  buffer_minutes: number
  days_of_week: number[]
  active_from: string | null
  active_until: string | null
  is_active: boolean
  required_qualifications: Qualification[]
}

export interface RouteTemplateCreate {
  school_id: number
  direction: RideDirection
  window_earliest: number
  window_latest: number
  duration_minutes: number
  buffer_minutes: number
  days_of_week: number[]
  active_from: string | null
  active_until: string | null
  required_qualification_codes: string[]
}

export interface CrewTemplate {
  id: number
  driver_id: number
  vehicle_id: number
  available_window_earliest: number
  available_window_latest: number
  days_of_week: number[]
  active_from: string | null
  active_until: string | null
  is_active: boolean
}

export interface CrewTemplateCreate {
  driver_id: number
  vehicle_id: number
  available_window_earliest: number
  available_window_latest: number
  days_of_week: number[]
  active_from: string | null
  active_until: string | null
}

export interface GenerateFromTemplatesResult {
  service_date: string
  runs_created: number
  runs_already_existing: number
  crews_created: number
  crews_already_existing: number
  crews_skipped_absent_driver_ids: number[]
  crews_skipped_out_of_service_template_ids: number[]
  crews_skipped_unlicensed_template_ids: number[]
}

export type SisImportAction =
  'created' | 'updated' | 'unchanged' | 'linked' | 'needs_review' | 'removal_requested' | 'error'

export interface SisImportRow {
  line: number
  source_id: string | null
  full_name: string | null
  action: SisImportAction
  detail: string | null
  student_id: number | null
}

export interface SisImportResult {
  dry_run: boolean
  counts: Record<SisImportAction, number>
  rows: SisImportRow[]
  rows_truncated: boolean
  ignored_non_student_rows: number
}

// Spec sections 11 and 14: unplanned work dispatch sends to a driver.
export type DispatchTaskKind =
  | 'cover_route'
  | 'assist_disabled_bus'
  | 'transfer_passengers'
  | 'return_to_school'
  | 'move_vehicle'
  | 'assist_driver'
  | 'emergency'
  | 'other'

export interface DispatchTask {
  id: number
  kind: DispatchTaskKind
  service_date: string
  start_minute: number
  end_minute: number
  driver_id: number
  driver_full_name: string
  vehicle_id: number | null
  vehicle_label: string | null
  location: string | null
  instructions: string
  status: AssignmentStatus
  cancelled: boolean
  created_at: string
  routes_needing_cover: string[]
}

export interface DispatchTaskCreate {
  kind: DispatchTaskKind
  service_date: string
  start_minute: number
  end_minute: number
  driver_id: number
  vehicle_id?: number | null
  location?: string | null
  instructions: string
}

export interface DriverDispatchTask {
  id: number
  kind: DispatchTaskKind
  service_date: string
  start_minute: number
  end_minute: number
  vehicle_label: string | null
  location: string | null
  instructions: string
  status: AssignmentStatus
  cancelled: boolean
}

// A field trip as its assigned driver sees it; start/end minutes are its
// span on the requested day.
export interface DriverFieldTrip {
  id: number
  status: TripStatus
  requesting_party: string
  origin: string
  destination: string
  departure_at: string
  return_at: string
  start_minute: number
  end_minute: number
  passenger_count: number
  vehicle_label: string | null
  bus_assistant_name: string | null
  trip_contact: string
  special_instructions: string | null
  destination_profile: DestinationProfile | null
}

// Something on a service date that needs dispatch's attention
// (services/api/src/isd_api/alerts.py lists what raises each kind).
export type AlertSeverity = 'critical' | 'warning'

export interface OperationalAlert {
  kind: string
  severity: AlertSeverity
  message: string
  entity_type: string
  entity_id: number
  minute: number | null
}

export interface DayAlerts {
  service_date: string
  district_time: string | null
  alerts: OperationalAlert[]
}
