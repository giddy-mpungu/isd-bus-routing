import { request, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { API_URL, statePath, type Role } from './env'

/**
 * Acting as several people in one test: each role gets its own browser
 * context with the session tests/seeded/auth.setup.ts saved, like separate
 * people on separate devices.
 */
export async function as(browser: Browser, role: Role, baseURL?: string): Promise<Page> {
  const context = await browser.newContext({
    storageState: statePath(role),
    baseURL,
    ignoreHTTPSErrors: true,
  })
  return context.newPage()
}

/** The API as a role (its session cookie), for setting up or checking state. */
export async function api(role: Role): Promise<APIRequestContext> {
  return request.newContext({
    baseURL: API_URL.endsWith('/') ? API_URL : `${API_URL}/`,
    storageState: statePath(role),
    ignoreHTTPSErrors: true,
  })
}

/** YYYY-MM-DD, `days` from today, by UTC as the web app counts days. */
export function day(days = 0): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10)
}
