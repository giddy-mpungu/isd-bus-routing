// Small hand-written typed fetch wrapper, not a generated OpenAPI
// client — the endpoint surface this console uses is small enough
// that keeping types in sync by hand is simpler than adding a
// codegen build step. Worth revisiting once the API surface grows.
//
// Every call sets credentials: 'include' so the httpOnly session
// cookie (services/api/src/isd_api/security.py) is sent/received —
// this client never reads or stores the token itself, since it can't:
// that's the point of httponly. See docs/adr/ (Phase 3 plan) for the
// full session-cookie reasoning.

import type {
  Absence,
  AbsenceCreate,
  AffectedAssignmentSubstitutes,
  Assignment,
  AssignmentPatch,
  AssignmentStatus,
  Crew,
  CrewCreate,
  CurrentUser,
  Driver,
  DriverAssignment,
  DriverCreate,
  ExpectedRiders,
  FamilyMember,
  GeographicKnowledgeOverride,
  GeographicKnowledgeOverrideCreate,
  Qualification,
  QualificationCreate,
  RidershipOverrideUpdate,
  Run,
  RunCreate,
  RunUpdate,
  School,
  SchoolCreate,
  ScheduleResult,
  Stop,
  StopCreate,
  Student,
  StudentCreate,
  Vehicle,
  VehicleCreate,
} from './types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body: unknown = await response.json()
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch {
      // No JSON body to read a detail message from — keep statusText.
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export async function login(email: string, password: string): Promise<void> {
  // OAuth2PasswordRequestForm on the backend expects form-encoded
  // username/password, not JSON — this is the one call that isn't.
  const body = new URLSearchParams({ username: email, password })
  await request<{ access_token: string; token_type: string }>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
}

export async function logout(): Promise<void> {
  await request<void>('/auth/logout', { method: 'POST' })
}

export async function getCurrentUser(): Promise<CurrentUser> {
  return request<CurrentUser>('/users/me')
}

export async function getSchools(): Promise<School[]> {
  return request<School[]>('/schools')
}

export async function createSchool(payload: SchoolCreate): Promise<School> {
  return request<School>('/schools', jsonInit('POST', payload))
}

export async function getQualifications(): Promise<Qualification[]> {
  return request<Qualification[]>('/qualifications')
}

export async function createQualification(payload: QualificationCreate): Promise<Qualification> {
  return request<Qualification>('/qualifications', jsonInit('POST', payload))
}

export async function getDrivers(): Promise<Driver[]> {
  return request<Driver[]>('/drivers')
}

export async function createDriver(payload: DriverCreate): Promise<Driver> {
  return request<Driver>('/drivers', jsonInit('POST', payload))
}

export async function getVehicles(): Promise<Vehicle[]> {
  return request<Vehicle[]>('/vehicles')
}

export async function createVehicle(payload: VehicleCreate): Promise<Vehicle> {
  return request<Vehicle>('/vehicles', jsonInit('POST', payload))
}

export async function getRuns(serviceDate: string): Promise<Run[]> {
  return request<Run[]>(`/runs?service_date=${serviceDate}`)
}

export async function getCrews(serviceDate: string): Promise<Crew[]> {
  return request<Crew[]>(`/crews?service_date=${serviceDate}`)
}

export async function createCrew(payload: CrewCreate): Promise<Crew> {
  return request<Crew>('/crews', jsonInit('POST', payload))
}

export async function updateCrewDriver(crewId: number, driverId: number): Promise<Crew> {
  return request<Crew>(`/crews/${crewId}`, jsonInit('PATCH', { driver_id: driverId }))
}

export async function createRun(payload: RunCreate): Promise<Run> {
  return request<Run>('/runs', jsonInit('POST', payload))
}

export async function updateRun(runId: number, payload: RunUpdate): Promise<Run> {
  return request<Run>(`/runs/${runId}`, jsonInit('PATCH', payload))
}

export async function getExpectedRiders(runId: number): Promise<ExpectedRiders> {
  return request<ExpectedRiders>(`/runs/${runId}/expected-riders`)
}

export async function getAssignments(serviceDate: string): Promise<Assignment[]> {
  return request<Assignment[]>(`/schedule/${serviceDate}/assignments`)
}

export async function runSchedule(serviceDate: string): Promise<ScheduleResult> {
  return request<ScheduleResult>('/schedule', jsonInit('POST', { service_date: serviceDate }))
}

export async function updateAssignment(id: number, patch: AssignmentPatch): Promise<Assignment> {
  return request<Assignment>(`/schedule/assignments/${id}`, jsonInit('PATCH', patch))
}

export async function deleteAssignment(id: number): Promise<void> {
  await request<void>(`/schedule/assignments/${id}`, { method: 'DELETE' })
}

export async function getMyAssignments(serviceDate: string): Promise<DriverAssignment[]> {
  return request<DriverAssignment[]>(`/schedule/${serviceDate}/my-assignments`)
}

export async function updateAssignmentStatus(
  id: number,
  status: AssignmentStatus,
): Promise<DriverAssignment> {
  return request<DriverAssignment>(
    `/schedule/assignments/${id}/status`,
    jsonInit('PATCH', { status }),
  )
}

export async function getStops(): Promise<Stop[]> {
  return request<Stop[]>('/stops')
}

export async function createStop(payload: StopCreate): Promise<Stop> {
  return request<Stop>('/stops', jsonInit('POST', payload))
}

export async function getStudents(): Promise<Student[]> {
  return request<Student[]>('/students')
}

export async function createStudent(payload: StudentCreate): Promise<Student> {
  return request<Student>('/students', jsonInit('POST', payload))
}

export async function linkGuardian(studentId: number, userId: number): Promise<void> {
  await request<void>(`/students/${studentId}/guardians`, jsonInit('POST', { user_id: userId }))
}

export async function getMyFamily(serviceDate: string): Promise<FamilyMember[]> {
  return request<FamilyMember[]>(`/students/my-family?service_date=${serviceDate}`)
}

export async function updateRidership(
  studentId: number,
  override: RidershipOverrideUpdate,
): Promise<void> {
  await request<void>(`/students/${studentId}/ridership`, jsonInit('PATCH', override))
}

export async function getAbsencesForDate(serviceDate: string): Promise<Absence[]> {
  return request<Absence[]>(`/absences?service_date=${serviceDate}`)
}

export async function createAbsence(driverId: number, payload: AbsenceCreate): Promise<Absence> {
  return request<Absence>(`/drivers/${driverId}/absences`, jsonInit('POST', payload))
}

export async function getSubstituteCandidates(
  driverId: number,
  serviceDate: string,
): Promise<AffectedAssignmentSubstitutes[]> {
  return request<AffectedAssignmentSubstitutes[]>(
    `/drivers/${driverId}/substitute-candidates?service_date=${serviceDate}`,
  )
}

export async function getGeographicKnowledgeOverrides(): Promise<GeographicKnowledgeOverride[]> {
  return request<GeographicKnowledgeOverride[]>('/geographic-knowledge')
}

export async function createGeographicKnowledgeOverride(
  payload: GeographicKnowledgeOverrideCreate,
): Promise<GeographicKnowledgeOverride> {
  return request<GeographicKnowledgeOverride>('/geographic-knowledge', jsonInit('POST', payload))
}
