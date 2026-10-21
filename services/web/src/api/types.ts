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
  // Phase 5.3: two-step sign-in is on / needed for this role.
  mfa_enabled?: boolean
  mfa_required?: boolean
  // Phase 5.4: signs in with the district account (single sign-on).
  sso_linked?: boolean
  // The language they chose for screens and emails (src/i18n), if any.
  preferred_language?: string | null
}

export interface User extends CurrentUser {
  created_at: string
}

export interface UserCreate {
  email: string
  // Left out: the person is emailed a link to choose their own.
  password?: string
  full_name: string
  role: Role
  driver_id?: number
  school_id?: number
  student_id?: number
  // The language of their emails until they choose one (src/i18n).
  preferred_language?: string
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
  // Spec section 3: an attendance zone is on file.
  has_zone?: boolean
}

export type QualificationKind = 'license' | 'vehicle_capability'

export interface Qualification {
  id: number
  code: string
  kind: QualificationKind
  description: string | null
  // Vehicle capabilities: students needing it ride in their wheelchair and
  // take one of the bus's wheelchair positions (spec section 6).
  takes_wheelchair_position: boolean
  is_active: boolean
}

// Spec section 15: tiered CDL A > CDL B > Class C (non-CDL). A driver may
// drive any vehicle whose required class is at or below their own.
export type LicenseClass = 'cdl_a' | 'cdl_b' | 'class_c'

export interface Driver {
  id: number
  full_name: string
  // The district's HR number (absence imports match on it).
  employee_id?: string | null
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
  vehicle_type: VehicleType | null
  wheelchair_positions: number | null
  turning_radius_m: number | null
  required_license_class: LicenseClass
  is_active: boolean
  qualifications: Qualification[]
}

// Spec section 6: US school bus types A (smallest) to D, a van, or other.
export type VehicleType = 'type_a' | 'type_b' | 'type_c' | 'type_d' | 'van' | 'other'

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
  // Route planning (spec section 2.2): students' ride time against the
  // bus's own time; 0 = the fastest route.
  ride_time_weight: number
  // Spec section 2.1: driver work-hour rules, each null (off) until the
  // district sets it. Minutes.
  max_duty_minutes: number | null
  break_after_minutes: number | null
  break_minutes: number | null
  min_rest_minutes: number | null
}

// Spec section 4.4: district ridership reporting rules.
export interface RidershipRulesUpdate {
  timezone: string
  am_cutoff_minute: number | null
  pm_cutoff_minute: number | null
  // Spec section 4.4: minutes before a run leaves when its route's stops
  // lock; null = no lock.
  route_lock_minutes?: number | null
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
  // Set when the run's route has ordered stops: 1-based position and the
  // planned minute of day (null when the route has no planned time).
  position?: number | null
  planned_minute?: number | null
  // False for riders whose stop isn't on the route.
  on_route?: boolean
  // Today's trip: a stop nobody rides from today is skipped; the others
  // have today's estimated arrival (minute of day).
  skipped?: boolean
  eta_minute?: number | null
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
  // True when `stops` is in the route's order.
  stops_ordered?: boolean
  // Road closures in force near today's trip; directions avoid them.
  closure_notes?: string[]
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
  // At the school: arriving in the morning, leaving in the afternoon.
  planned_school_minute?: number | null
  expected_school_minute?: number | null
  delay_minutes?: number
  running_late?: boolean
  eta_basis?: string | null
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
  takes_wheelchair_position?: boolean
}

export interface QualificationUpdate {
  description?: string
  is_active?: boolean
}

export interface DriverCreate {
  full_name: string
  employee_id?: string
  max_continuous_minutes?: number
  qualification_codes: string[]
  license_class?: LicenseClass
}

export interface DriverUpdate {
  full_name?: string
  // null clears it.
  employee_id?: string | null
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
  vehicle_type?: VehicleType
  wheelchair_positions?: number
  turning_radius_m?: number
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
  // null clears these three.
  vehicle_type?: VehicleType | null
  wheelchair_positions?: number | null
  turning_radius_m?: number | null
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
  // Set for students imported from the SIS: their name, school and grade
  // are owned by the SIS and can't be edited here.
  external_id?: string | null
  // "PK", "K" or "1".."12".
  grade?: string | null
  needs_specialized_transport?: boolean
  hazardous_route?: boolean
  // What the bus must have for this student (qualification tags).
  accommodations?: Qualification[]
  // Whether a home location is on file. The home itself is admin-only
  // (GET /students/{id}/home) and never part of this record.
  has_home?: boolean
  eligibility?: Eligibility | null
  // FERPA retention: left the district; personal data deleted after delete_after.
  withdrawn_on?: string | null
  delete_after?: string | null
}

export type GradeBand = 'prek' | 'elementary' | 'middle' | 'high' | 'specialized'

export interface Eligibility {
  eligible: boolean
  reason: string
  miles_from_school: number | null
  band: GradeBand | null
}

export interface StudentHome {
  address: string
  location_lat: number
  location_lon: number
  source: 'census' | 'manual'
  matched_address: string | null
  updated_at: string
}

// Just the address: looked up with the US Census geocoder. With both
// coordinates: a location placed by hand on the map.
export interface StudentHomeUpdate {
  address: string
  location_lat?: number
  location_lon?: number
}

export interface TransportationRules {
  eligibility_miles: number
  walk_miles: Record<GradeBand, number>
  ride_minutes: Record<GradeBand, number>
  min_stop_spacing_miles: number
  band_labels: Record<GradeBand, string>
  is_default: boolean
}

export interface TransportationRulesUpdate {
  eligibility_miles: number
  walk_miles: Record<GradeBand, number>
  ride_minutes: Record<GradeBand, number>
  min_stop_spacing_miles?: number
}

// Spec section 3.1 stop proposals (admin only).
export type StopProposalKind = 'new' | 'existing' | 'curb'
export type StopProposalStatus = 'pending' | 'approved' | 'rejected'

export interface StopProposalRider {
  student_id: number
  full_name: string
  walk_miles: number | null
  walk_limit_miles: number
}

export interface StopProposal {
  id: number
  school_id: number
  kind: StopProposalKind
  status: StopProposalStatus
  stop_id: number | null
  label: string
  location_lat: number
  location_lon: number
  riders: StopProposalRider[]
  warnings: string[]
  created_at: string
  decided_at: string | null
}

export interface StopProposalsGenerated {
  proposals: StopProposal[]
  students_considered: number
  already_have_stop: number
  no_home: number
  not_eligible: number
}

export interface StopProposalUpdate {
  label?: string
  location_lat?: number
  location_lon?: number
}

// Only the fields sent are changed; stop_id: null clears the stop.
export interface StudentUpdate {
  full_name?: string
  school_id?: number
  stop_id?: number | null
  default_ridership?: RidershipDefault
  // null clears it (not allowed for SIS students).
  grade?: string | null
  needs_specialized_transport?: boolean
  hazardous_route?: boolean
  accommodation_codes?: string[]
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
  grade?: string | null
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
  // Today's estimated arrival at the child's stop, when riding that leg.
  am_eta?: StopEta | null
  pm_eta?: StopEta | null
}

export interface StopEta {
  // Spec section 18 "assigned route": the bus, and the stop's place on it.
  bus_label?: string | null
  stop_position?: number | null
  stop_count?: number | null
  stop_label: string
  eta_minute: number
  planned_minute: number | null
  // Moved materially (5+ minutes) from the plan.
  changed: boolean
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
  // Vehicle defects: where the report stands.
  status?: DefectStatus
  resolution_note?: string | null
}

export type DefectStatus = 'open' | 'out_of_service' | 'fixed'

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
  // Spec section 9 "direction of travel": null until the bus has moved.
  heading_degrees: number | null
  heading: string | null
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
  // The school it leaves from and returns to, when it's one of ours.
  origin_school_id: number | null
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
  origin_school_id?: number
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
  // Its window comes from the school's bells each day; the window above
  // is then the regular day's.
  follows_bells?: boolean
  required_qualifications: Qualification[]
  // In visiting order.
  stops?: RouteStop[]
}

export interface RouteStop {
  position: number
  stop_id: number
  stop_label: string
  location_lat: number
  location_lon: number
  minutes_from_start: number | null
}

// A planned order and times for a route's stops (decision support).
export interface PlannedRouteStop {
  position: number
  stop_id: number
  stop_label: string
  minutes_from_start: number
  riders: number
  ride_minutes: number
  ride_limit_minutes: number | null
}

export interface RoutePlan {
  stops: PlannedRouteStop[]
  total_minutes: number
  current_duration_minutes: number
  window_minutes: number
  fits_window: boolean
  ride_limits_met: boolean
  violations: string[]
  applied: boolean
  travel_estimate: string
}

export interface RouteStopWrite {
  stop_id: number
  minutes_from_start: number | null
}

export interface RouteTemplateCreate {
  school_id: number
  direction: RideDirection
  // Left out when the route follows the school's bells.
  window_earliest?: number
  window_latest?: number
  follows_bells?: boolean
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

// Operational reports (services/api/src/isd_api/reports.py).
export type ReportName =
  'assignments' | 'field-trips' | 'absences' | 'driver-reports' | 'dispatch-tasks' | 'positions'

export type ReportCell = string | number | null

export interface Report {
  name: ReportName
  title: string
  start: string
  end: string
  columns: string[]
  // The first rows only; `total_rows` is how many the CSV has.
  rows: ReportCell[][]
  total_rows: number
  summary: Record<string, ReportCell>
}

export interface PositionSample {
  location_lat: number
  location_lon: number
  recorded_at: string
}

// Turn-by-turn directions through a run's stops today.
export interface DirectionsWaypoint {
  label: string
  lat: number
  lon: number
}

export interface DirectionsResult {
  available: boolean
  reason: string | null
  waypoints: DirectionsWaypoint[]
  distance_m: number
  duration_s: number
  // [lat, lon] pairs along the route.
  coordinates: [number, number][]
  legs: { to_label: string; distance_m: number; duration_s: number }[]
  steps: {
    instruction: string
    name: string
    distance_m: number
    duration_s: number
    leg: number
  }[]
  attribution: string
}

// Spec section 10: temporary road closures to route around.
export type ClosureKind =
  | 'road_closed'
  | 'collision'
  | 'construction'
  | 'flooding'
  | 'police_activity'
  | 'severe_congestion'
  | 'other'

export interface RoadClosure {
  id: number
  kind: ClosureKind
  note: string
  location_lat: number
  location_lon: number
  radius_m: number
  starts_at: string
  ends_at: string | null
  cleared: boolean
  active: boolean
  affected_runs: { assignment_id: number; description: string; stop_inside: string | null }[]
}

export interface RoadClosureCreate {
  kind: ClosureKind
  note: string
  location_lat: number
  location_lon: number
  radius_m: number
  starts_at?: string | null
  ends_at?: string | null
}

// Phase 5.3: after a correct password, what's still needed: a code
// ("verify") or setting up an authenticator ("setup").
export type MfaStep = 'verify' | 'setup'

export interface LoginResult {
  access_token: string | null
  token_type: string
  mfa: MfaStep | null
  recovery_codes_left: number | null
}

export interface MfaSetup {
  secret: string
  otpauth_uri: string
}

export interface MfaStatus {
  allowed: boolean
  required: boolean
  enabled: boolean
  recovery_codes_left: number
}

// Phase 5.2: what the sign-in page can offer.
export interface AuthOptions {
  email_enabled: boolean
  // Phase 5.4: the single sign-on button's wording; null when SSO is off.
  sso_label?: string | null
}

// Phase 5.1: a one-time link to set a new password. The token is in the
// fragment (after #), which browsers never send to a server.
export interface ResetLink {
  reset_path: string
  expires_at: string
}

// Phase 5.5: a parent's email choices.
export interface NotificationSettings {
  eta_emails: boolean
}

// The scheduled OneRoster sync (spec section 19).
export interface SisSyncRun {
  id: number
  trigger: 'scheduled' | 'manual'
  status: 'running' | 'ok' | 'needs_attention' | 'failed'
  started_at: string
  finished_at: string | null
  counts: Partial<Record<SisImportAction, number>> | null
  problems: SisImportRow[] | null
  error: string | null
}

export interface SisSyncStatus {
  configured: boolean
  sync_time: string
  runs: SisSyncRun[]
}

// FERPA: one line of "who viewed this student".
export interface StudentAccess {
  day: string
  first_at: string
  user_id: number
  user_name: string
  user_role: Role
  what: string
  what_label: string
}

// FERPA: a family's request to correct a student's record.
export interface Correction {
  id: number
  student_id: number
  student_name: string
  requested_by: string
  created_at: string
  what_is_wrong: string
  should_say: string
  status: 'open' | 'accepted' | 'declined'
  decided_at: string | null
  response: string | null
}

// --- Bell schedules (services/api/src/isd_api/bells.py) ---

// Minutes around the bells: morning buses arrive between
// arrive_earliest_before and arrive_latest_before minutes before the first
// bell; afternoon buses leave between leave_earliest_after and
// leave_latest_after minutes after dismissal.
export interface BellOffsets {
  arrive_earliest_before: number
  arrive_latest_before: number
  leave_earliest_after: number
  leave_latest_after: number
}

export interface BellRules extends BellOffsets {
  is_default: boolean
}

export interface BellSchedule {
  id: number
  school_id: number
  name: string
  first_bell_minute: number
  dismissal_minute: number
  is_regular: boolean
}

export interface BellScheduleCreate {
  name: string
  first_bell_minute: number
  dismissal_minute: number
  is_regular?: boolean
}

export type BellScheduleUpdate = Partial<BellScheduleCreate>

export interface BellCalendarDay {
  id: number
  school_id: number
  school_name: string
  service_date: string
  bell_schedule_id: number
  schedule_name: string
}

export interface SchoolBells {
  school_id: number
  school_name: string
  schedules: BellSchedule[]
  own_offsets: BellOffsets | null
  offsets_in_use: BellOffsets
  upcoming_days: BellCalendarDay[]
}

// What a change to bells did to runs already generated for today and later.
export interface BellChange {
  runs_updated: number
  assigned_runs_moved: number
  skipped_schools: string[]
}

// Spec sections 13 and 19: absences from the district's HR export.
export interface AbsenceImportRow {
  line: number
  driver: string
  date: string
  outcome: 'created' | 'unchanged' | 'error'
  message: string | null
}

export interface AbsenceImport {
  applied: boolean
  rows: AbsenceImportRow[]
}

export interface BellImportRow {
  line: number
  school: string
  schedule: string
  outcome: 'created' | 'updated' | 'unchanged' | 'error'
  message: string | null
}

export interface BellImport {
  applied: boolean
  rows: BellImportRow[]
  change: BellChange | null
}

// --- Fleet maintenance (services/api/src/isd_api/maintenance.py) ---

export type MaintenanceKind = 'planned' | 'repair' | 'inspection'

export interface MaintenanceWindow {
  id: number
  vehicle_id: number
  vehicle_label: string
  kind: MaintenanceKind
  // District wall-clock times ("2026-10-20T06:00:00"); no end: until
  // marked back in service.
  starts_at: string
  ends_at: string | null
  reason: string
  driver_report_id: number | null
  current: boolean
}

export interface MaintenanceWindowCreate {
  vehicle_id: number
  kind: MaintenanceKind
  starts_at: string
  ends_at: string | null
  reason: string
}

export interface ServiceRecord {
  id: number
  vehicle_id: number
  performed_on: string
  work: string
  performed_by: string
  created_at: string
}

export interface ServiceRecordCreate {
  performed_on: string
  work: string
  performed_by: string
  next_service_due_on?: string | null
  inspection_expires_on?: string | null
}

export interface VehicleMaintenance {
  vehicle_id: number
  vehicle_label: string
  service_due_on: string | null
  inspection_expires_on: string | null
  service_log: ServiceRecord[]
  windows: MaintenanceWindow[]
}

export interface MaintenanceDue {
  vehicle_id: number
  vehicle_label: string
  severity: 'critical' | 'warning'
  message: string
}

export interface DefectReport extends DriverReport {
  driver_name: string
  vehicle_label: string | null
}

export interface SpareVehicle {
  vehicle_id: number
  label: string
  allowable_capacity: number | null
  spare_seats: number | null
}

export interface Spares {
  crew_id: number
  current_vehicle_label: string
  spares: SpareVehicle[]
}
