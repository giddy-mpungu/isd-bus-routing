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

export interface School {
  id: number
  name: string
  location_lat: number
  location_lon: number
}

export type QualificationKind = 'license' | 'vehicle_capability'

export interface Qualification {
  id: number
  code: string
  kind: QualificationKind
  description: string | null
}

export interface Driver {
  id: number
  full_name: string
  max_continuous_minutes: number | null
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
}

export interface ScheduleResult {
  crews_used: number
  assignments: Assignment[]
}

export interface AssignmentPatch {
  crew_id?: number
  start_minute?: number
  end_minute?: number
  locked?: boolean
}

export type AssignmentStatus = 'scheduled' | 'in_progress' | 'completed' | 'no_show'

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

export interface DriverCreate {
  full_name: string
  max_continuous_minutes?: number
  qualification_codes: string[]
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

export interface Stop {
  id: number
  label: string
  location_lat: number
  location_lon: number
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

export interface GeographicKnowledgeOverride {
  id: number
  location_lat: number
  location_lon: number
  category: GeographicKnowledgeCategory
  note: string
  created_at: string
}

export interface GeographicKnowledgeOverrideCreate {
  location_lat: number
  location_lon: number
  category: GeographicKnowledgeCategory
  note: string
}
