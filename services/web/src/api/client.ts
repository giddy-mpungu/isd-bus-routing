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
  Assignment,
  AssignmentPatch,
  Crew,
  CurrentUser,
  Driver,
  Run,
  School,
  ScheduleResult,
  Vehicle,
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

export async function getDrivers(): Promise<Driver[]> {
  return request<Driver[]>('/drivers')
}

export async function getVehicles(): Promise<Vehicle[]> {
  return request<Vehicle[]>('/vehicles')
}

export async function getRuns(serviceDate: string): Promise<Run[]> {
  return request<Run[]>(`/runs?service_date=${serviceDate}`)
}

export async function getCrews(serviceDate: string): Promise<Crew[]> {
  return request<Crew[]>(`/crews?service_date=${serviceDate}`)
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
