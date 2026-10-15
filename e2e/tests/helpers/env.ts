import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

/** Where the harness put the system under test (playwright.config.ts). */
export const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8090'
export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? ''
export const OUT = process.env.E2E_OUT ?? join(process.cwd(), '.out', 'local')

mkdirSync(join(OUT, 'state'), { recursive: true })

export type Role =
  'transportation_admin' | 'dispatcher' | 'school_admin' | 'driver' | 'parent' | 'student'

/** One login the harness created (scripts/seed_demo.py prints these). */
export interface Account {
  role: Role
  email: string
  password: string
  full_name: string
  note: string
}

/** The seeded demo district's logins, read from the harness's output. */
export function seededAccounts(): Account[] {
  return JSON.parse(readFileSync(join(OUT, 'credentials.json'), 'utf8')) as Account[]
}

/** The first seeded login with this role. */
export function account(role: Role): Account {
  const found = seededAccounts().find((a) => a.role === role)
  if (!found) throw new Error(`The seed made no ${role} login`)
  return found
}

/** Saved browser session for a role (seeded/auth.setup.ts writes it). */
export function statePath(role: Role): string {
  return join(OUT, 'state', `${role}.json`)
}

/** Authenticator secrets of accounts that set up two-step sign-in, by email. */
export function mfaSecretsPath(): string {
  return join(OUT, 'state', 'mfa-secrets.json')
}
