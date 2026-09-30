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
  Announcement,
  AnnouncementCreate,
  Assignment,
  AssignmentPatch,
  AssignmentStatus,
  AuditLogEntry,
  AuditLogQuery,
  BusPosition,
  Crew,
  CrewCreate,
  CrewTemplate,
  CrewTemplateCreate,
  CurrentUser,
  DayAlerts,
  DirectionsResult,
  DestinationProfile,
  DestinationProfileCreate,
  DispatchTask,
  DispatchTaskCreate,
  Driver,
  DriverAssignment,
  DriverCreate,
  DriverDispatchTask,
  DriverFieldTrip,
  DriverReport,
  DriverReportCreate,
  DriverUpdate,
  ExpectedRiders,
  FamilyMember,
  FieldTrip,
  FieldTripConflictCheck,
  FieldTripCreate,
  FieldTripObservedDuration,
  FieldTripUpdate,
  GenerateFromTemplatesResult,
  GeographicKnowledgeOverride,
  GeographicKnowledgeOverrideCreate,
  Guardian,
  ObservedRunDuration,
  OptimizationSettings,
  OptimizationSettingsUpdate,
  PositionSample,
  PositionUpdate,
  Qualification,
  QualificationCreate,
  QualificationUpdate,
  Report,
  ReportName,
  RideDirection,
  RidershipOverrideUpdate,
  RidershipRules,
  RidershipRulesUpdate,
  ResetLink,
  RoadClosure,
  RoadClosureCreate,
  RoutePlan,
  RouteStop,
  RouteStopWrite,
  RouteTemplate,
  RouteTemplateCreate,
  Run,
  RunCreate,
  RunUpdate,
  ScheduleResult,
  School,
  SchoolAssignment,
  SchoolCreate,
  SchoolUpdate,
  SisImportResult,
  Stop,
  StopCreate,
  StopProposal,
  StopProposalsGenerated,
  StopProposalUpdate,
  StopUpdate,
  Student,
  StudentCreate,
  StudentHome,
  StudentHomeUpdate,
  StudentUpdate,
  TransportationRules,
  TransportationRulesUpdate,
  User,
  UserCreate,
  UserUpdate,
  Vehicle,
  VehicleCreate,
  VehiclePosition,
  VehicleUpdate,
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

// Ends the account's other sessions; the response renews this one's cookie.
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await request<unknown>(
    '/auth/change-password',
    jsonInit('POST', { current_password: currentPassword, new_password: newPassword }),
  )
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  await request<void>(
    '/auth/reset-password',
    jsonInit('POST', { token, new_password: newPassword }),
  )
}

export async function issueResetLink(userId: number): Promise<ResetLink> {
  return request<ResetLink>(`/users/${userId}/reset-link`, jsonInit('POST', {}))
}

export async function getUsers(): Promise<User[]> {
  return request<User[]>('/users')
}

export async function createUser(payload: UserCreate): Promise<User> {
  return request<User>('/users', jsonInit('POST', payload))
}

export async function updateUser(id: number, payload: UserUpdate): Promise<User> {
  return request<User>(`/users/${id}`, jsonInit('PATCH', payload))
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

export async function updateQualification(
  id: number,
  payload: QualificationUpdate,
): Promise<Qualification> {
  return request<Qualification>(`/qualifications/${id}`, jsonInit('PATCH', payload))
}

export async function getDrivers(): Promise<Driver[]> {
  return request<Driver[]>('/drivers')
}

export async function createDriver(payload: DriverCreate): Promise<Driver> {
  return request<Driver>('/drivers', jsonInit('POST', payload))
}

export async function updateDriver(id: number, payload: DriverUpdate): Promise<Driver> {
  return request<Driver>(`/drivers/${id}`, jsonInit('PATCH', payload))
}

export async function getVehicles(): Promise<Vehicle[]> {
  return request<Vehicle[]>('/vehicles')
}

export async function createVehicle(payload: VehicleCreate): Promise<Vehicle> {
  return request<Vehicle>('/vehicles', jsonInit('POST', payload))
}

export async function updateVehicle(id: number, payload: VehicleUpdate): Promise<Vehicle> {
  return request<Vehicle>(`/vehicles/${id}`, jsonInit('PATCH', payload))
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

export async function getObservedRunDuration(
  schoolId: number,
  direction: RideDirection,
): Promise<ObservedRunDuration> {
  return request<ObservedRunDuration>(
    `/runs/observed-duration?school_id=${schoolId}&direction=${direction}`,
  )
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

// Spec section 14 "Received": the tablet has the day's assignments.
export async function markAssignmentsReceived(serviceDate: string): Promise<DriverAssignment[]> {
  return request<DriverAssignment[]>(
    `/schedule/${serviceDate}/my-assignments/receipt`,
    jsonInit('POST', {}),
  )
}

export async function getSchoolAssignments(serviceDate: string): Promise<SchoolAssignment[]> {
  return request<SchoolAssignment[]>(`/schedule/${serviceDate}/school-assignments`)
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

export async function updateStop(id: number, payload: StopUpdate): Promise<Stop> {
  return request<Stop>(`/stops/${id}`, jsonInit('PATCH', payload))
}

export async function deleteStop(id: number): Promise<void> {
  await request<void>(`/stops/${id}`, { method: 'DELETE' })
}

export async function getStudents(): Promise<Student[]> {
  return request<Student[]>('/students')
}

export async function createStudent(payload: StudentCreate): Promise<Student> {
  return request<Student>('/students', jsonInit('POST', payload))
}

export async function updateStudent(id: number, payload: StudentUpdate): Promise<Student> {
  return request<Student>(`/students/${id}`, jsonInit('PATCH', payload))
}

// A student's home: transportation admins only. 404 means none on file.
export async function getStudentHome(studentId: number): Promise<StudentHome> {
  return request<StudentHome>(`/students/${studentId}/home`)
}

export async function setStudentHome(
  studentId: number,
  payload: StudentHomeUpdate,
): Promise<StudentHome> {
  return request<StudentHome>(`/students/${studentId}/home`, jsonInit('PUT', payload))
}

export async function deleteStudentHome(studentId: number): Promise<void> {
  return request<void>(`/students/${studentId}/home`, { method: 'DELETE' })
}

export async function getTransportationRules(): Promise<TransportationRules> {
  return request<TransportationRules>('/transportation-rules')
}

export async function updateTransportationRules(
  payload: TransportationRulesUpdate,
): Promise<TransportationRules> {
  return request<TransportationRules>('/transportation-rules', jsonInit('PUT', payload))
}

export async function getGuardians(studentId: number): Promise<Guardian[]> {
  return request<Guardian[]>(`/students/${studentId}/guardians`)
}

export async function linkGuardian(studentId: number, userId: number): Promise<void> {
  await request<void>(`/students/${studentId}/guardians`, jsonInit('POST', { user_id: userId }))
}

export async function unlinkGuardian(studentId: number, userId: number): Promise<void> {
  await request<void>(`/students/${studentId}/guardians/${userId}`, { method: 'DELETE' })
}

export async function updateSchool(id: number, payload: SchoolUpdate): Promise<School> {
  return request<School>(`/schools/${id}`, jsonInit('PATCH', payload))
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

export async function createDriverReport(
  driverId: number,
  payload: DriverReportCreate,
): Promise<DriverReport> {
  return request<DriverReport>(`/drivers/${driverId}/reports`, jsonInit('POST', payload))
}

export async function getDriverReportsForDate(serviceDate: string): Promise<DriverReport[]> {
  return request<DriverReport[]>(`/reports?service_date=${serviceDate}`)
}

export async function getAnnouncements(): Promise<Announcement[]> {
  return request<Announcement[]>('/announcements')
}

export async function getMyAnnouncements(): Promise<Announcement[]> {
  return request<Announcement[]>('/announcements/mine')
}

export async function createAnnouncement(payload: AnnouncementCreate): Promise<Announcement> {
  return request<Announcement>('/announcements', jsonInit('POST', payload))
}

export async function reportPosition(driverId: number, payload: PositionUpdate): Promise<void> {
  await request<void>(`/drivers/${driverId}/position`, jsonInit('PUT', payload))
}

export async function getFleetPositions(serviceDate: string): Promise<VehiclePosition[]> {
  return request<VehiclePosition[]>(`/schedule/${serviceDate}/fleet-positions`)
}

export async function getFieldTrips(departureDate: string): Promise<FieldTrip[]> {
  return request<FieldTrip[]>(`/field-trips?departure_date=${departureDate}`)
}

export async function createFieldTrip(payload: FieldTripCreate): Promise<FieldTrip> {
  return request<FieldTrip>('/field-trips', jsonInit('POST', payload))
}

export async function updateFieldTrip(
  tripId: number,
  payload: FieldTripUpdate,
): Promise<FieldTrip> {
  return request<FieldTrip>(`/field-trips/${tripId}`, jsonInit('PATCH', payload))
}

export async function getFieldTripObservedDuration(params: {
  destination?: string
  destinationProfileId?: number
}): Promise<FieldTripObservedDuration> {
  const query = new URLSearchParams()
  if (params.destinationProfileId != null) {
    query.set('destination_profile_id', String(params.destinationProfileId))
  } else if (params.destination) {
    query.set('destination', params.destination)
  }
  return request<FieldTripObservedDuration>(`/field-trips/observed-duration?${query.toString()}`)
}

export async function getDestinationProfiles(): Promise<DestinationProfile[]> {
  return request<DestinationProfile[]>('/destination-profiles')
}

export async function createDestinationProfile(
  payload: DestinationProfileCreate,
): Promise<DestinationProfile> {
  return request<DestinationProfile>('/destination-profiles', jsonInit('POST', payload))
}

export async function getFieldTripConflicts(
  tripId: number,
  driverId?: number,
  vehicleId?: number,
): Promise<FieldTripConflictCheck> {
  const params = new URLSearchParams()
  if (driverId != null) {
    params.set('driver_id', String(driverId))
  }
  if (vehicleId != null) {
    params.set('vehicle_id', String(vehicleId))
  }
  const query = params.toString()
  return request<FieldTripConflictCheck>(
    `/field-trips/${tripId}/conflicts${query ? `?${query}` : ''}`,
  )
}

export async function getBusPosition(
  studentId: number,
  serviceDate: string,
  direction: RideDirection,
): Promise<BusPosition> {
  return request<BusPosition>(
    `/students/${studentId}/bus-position?service_date=${serviceDate}&direction=${direction}`,
  )
}

export async function getAuditLog(query: AuditLogQuery): Promise<AuditLogEntry[]> {
  const params = new URLSearchParams()
  if (query.entity_type) {
    params.set('entity_type', query.entity_type)
  }
  if (query.entity_id != null) {
    params.set('entity_id', String(query.entity_id))
  }
  if (query.limit != null) {
    params.set('limit', String(query.limit))
  }
  if (query.offset != null) {
    params.set('offset', String(query.offset))
  }
  const search = params.toString()
  return request<AuditLogEntry[]>(`/audit-log${search ? `?${search}` : ''}`)
}

export async function getAuditLogEntityTypes(): Promise<string[]> {
  return request<string[]>('/audit-log/entity-types')
}

export async function getRouteTemplates(): Promise<RouteTemplate[]> {
  return request<RouteTemplate[]>('/route-templates')
}

export async function createRouteTemplate(payload: RouteTemplateCreate): Promise<RouteTemplate> {
  return request<RouteTemplate>('/route-templates', jsonInit('POST', payload))
}

export async function setRouteTemplateActive(
  templateId: number,
  isActive: boolean,
): Promise<RouteTemplate> {
  return request<RouteTemplate>(
    `/route-templates/${templateId}`,
    jsonInit('PATCH', { is_active: isActive }),
  )
}

export async function getCrewTemplates(): Promise<CrewTemplate[]> {
  return request<CrewTemplate[]>('/crew-templates')
}

export async function createCrewTemplate(payload: CrewTemplateCreate): Promise<CrewTemplate> {
  return request<CrewTemplate>('/crew-templates', jsonInit('POST', payload))
}

export async function setCrewTemplateActive(
  templateId: number,
  isActive: boolean,
): Promise<CrewTemplate> {
  return request<CrewTemplate>(
    `/crew-templates/${templateId}`,
    jsonInit('PATCH', { is_active: isActive }),
  )
}

export async function generateFromTemplates(
  serviceDate: string,
): Promise<GenerateFromTemplatesResult> {
  return request<GenerateFromTemplatesResult>(`/schedule/${serviceDate}/generate-from-templates`, {
    method: 'POST',
  })
}

export async function getOptimizationSettings(): Promise<OptimizationSettings> {
  return request<OptimizationSettings>('/optimization-settings')
}

export async function updateOptimizationSettings(
  payload: OptimizationSettingsUpdate,
): Promise<OptimizationSettings> {
  return request<OptimizationSettings>('/optimization-settings', jsonInit('PUT', payload))
}

export async function getRidershipRules(): Promise<RidershipRules> {
  return request<RidershipRules>('/ridership-rules')
}

export async function updateRidershipRules(payload: RidershipRulesUpdate): Promise<RidershipRules> {
  return request<RidershipRules>('/ridership-rules', jsonInit('PUT', payload))
}

export async function updateSchoolExternalId(
  schoolId: number,
  externalId: string | null,
): Promise<School> {
  return request<School>(`/schools/${schoolId}`, jsonInit('PATCH', { external_id: externalId }))
}

export async function importSisStudents(
  file: File,
  dryRun: boolean,
  linkByName: boolean,
): Promise<SisImportResult> {
  // Multipart, so no JSON Content-Type: the browser sets the boundary itself.
  const form = new FormData()
  form.append('file', file)
  form.append('dry_run', String(dryRun))
  form.append('link_by_name', String(linkByName))
  return request<SisImportResult>('/integrations/sis/students/import', {
    method: 'POST',
    body: form,
  })
}

export async function getDispatchTasks(serviceDate: string): Promise<DispatchTask[]> {
  return request<DispatchTask[]>(`/dispatch-tasks?service_date=${serviceDate}`)
}

export async function createDispatchTask(payload: DispatchTaskCreate): Promise<DispatchTask> {
  return request<DispatchTask>('/dispatch-tasks', jsonInit('POST', payload))
}

export async function cancelDispatchTask(id: number): Promise<DispatchTask> {
  return request<DispatchTask>(`/dispatch-tasks/${id}/cancel`, jsonInit('POST', {}))
}

export async function getMyDispatchTasks(serviceDate: string): Promise<DriverDispatchTask[]> {
  return request<DriverDispatchTask[]>(`/dispatch-tasks/mine/${serviceDate}`)
}

export async function markDispatchTasksReceived(
  serviceDate: string,
): Promise<DriverDispatchTask[]> {
  return request<DriverDispatchTask[]>(
    `/dispatch-tasks/mine/${serviceDate}/receipt`,
    jsonInit('POST', {}),
  )
}

export async function updateDispatchTaskStatus(
  id: number,
  status: AssignmentStatus,
): Promise<DriverDispatchTask> {
  return request<DriverDispatchTask>(`/dispatch-tasks/${id}/status`, jsonInit('PATCH', { status }))
}

export async function getMyFieldTrips(serviceDate: string): Promise<DriverFieldTrip[]> {
  return request<DriverFieldTrip[]>(`/field-trips/mine/${serviceDate}`)
}

export async function getAlerts(serviceDate: string): Promise<DayAlerts> {
  return request<DayAlerts>(`/alerts?service_date=${serviceDate}`)
}

export async function getReport(name: ReportName, start: string, end: string): Promise<Report> {
  return request<Report>(`/reports/${name}?start=${start}&end=${end}`)
}

// A plain link, so the browser downloads the file itself with the session
// cookie; nothing has to be assembled in page script.
export function reportCsvUrl(name: ReportName, start: string, end: string): string {
  return `${API_BASE_URL}/reports/${name}/csv?start=${start}&end=${end}`
}

export async function getCrewTrack(serviceDate: string, crewId: number): Promise<PositionSample[]> {
  return request<PositionSample[]>(`/schedule/${serviceDate}/fleet-positions/${crewId}/track`)
}

export async function getRouteStops(templateId: number): Promise<RouteStop[]> {
  return request<RouteStop[]>(`/route-templates/${templateId}/stops`)
}

// Replaces the route's whole stop list, in visiting order.
export async function setRouteStops(
  templateId: number,
  stops: RouteStopWrite[],
): Promise<RouteStop[]> {
  return request<RouteStop[]>(`/route-templates/${templateId}/stops`, jsonInit('PUT', { stops }))
}

export async function generateStopProposals(schoolId: number): Promise<StopProposalsGenerated> {
  return request<StopProposalsGenerated>(
    '/stop-proposals/generate',
    jsonInit('POST', { school_id: schoolId }),
  )
}

export async function getStopProposals(schoolId: number): Promise<StopProposal[]> {
  return request<StopProposal[]>(`/stop-proposals?school_id=${schoolId}`)
}

export async function updateStopProposal(
  id: number,
  patch: StopProposalUpdate,
): Promise<StopProposal> {
  return request<StopProposal>(`/stop-proposals/${id}`, jsonInit('PATCH', patch))
}

export async function approveStopProposal(id: number): Promise<StopProposal> {
  return request<StopProposal>(`/stop-proposals/${id}/approve`, jsonInit('POST', {}))
}

export async function rejectStopProposal(id: number): Promise<StopProposal> {
  return request<StopProposal>(`/stop-proposals/${id}/reject`, jsonInit('POST', {}))
}

// Plans the saved stops' order and times; with apply, saves them and the
// route's duration.
export async function planRouteStops(templateId: number, apply: boolean): Promise<RoutePlan> {
  return request<RoutePlan>(
    `/route-templates/${templateId}/stops/plan`,
    jsonInit('POST', { apply }),
  )
}

// Directions through the run's stops today; `from` starts at the tablet's
// position.
export async function getDirections(
  assignmentId: number,
  from?: { lat: number; lon: number },
): Promise<DirectionsResult> {
  const query = from ? `?from_lat=${from.lat}&from_lon=${from.lon}` : ''
  return request<DirectionsResult>(`/schedule/assignments/${assignmentId}/directions${query}`)
}

export async function getRoadClosures(): Promise<RoadClosure[]> {
  return request<RoadClosure[]>('/road-closures')
}

export async function createRoadClosure(payload: RoadClosureCreate): Promise<RoadClosure> {
  return request<RoadClosure>('/road-closures', jsonInit('POST', payload))
}

export async function clearRoadClosure(id: number): Promise<RoadClosure> {
  return request<RoadClosure>(`/road-closures/${id}/clear`, jsonInit('POST', {}))
}
