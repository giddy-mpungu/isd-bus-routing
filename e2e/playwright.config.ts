import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests against a running isd-bus-routing (README.md here).
 *
 * A harness script starts the system and says where it is:
 *   E2E_BASE_URL     the web app, e.g. https://localhost
 *   E2E_API_URL      the API, e.g. https://localhost/api
 *   E2E_MAILPIT_URL  the captured inbox, if mail is set up (else mail tests skip)
 *   E2E_OUT          a folder for this run's logins and saved sessions
 *
 * Projects:
 *   install  a first-time install by the runbook: the first administrator,
 *            security headers, mail (scripts/fresh-install.sh)
 *   setup    signs in once as every seeded role and saves the sessions
 *   seeded   every page as each role of the demo district (read-only)
 *   journeys each role's work end to end, after `seeded` (they change data)
 *   integrations  outside systems: single sign-on, the SIS, the worker's
 *            emails (e2e-heavy.yml; the harness starts what they need)
 */
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:4173'

export default defineConfig({
  testDir: './tests',
  // One system, shared state (a schedule, a bus out of service): one
  // worker, in file order, so tests never race each other.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL,
    // The fresh install serves HTTPS with Caddy's own local certificate.
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  projects: [
    { name: 'install', testMatch: /install\/.*\.spec\.ts/ },
    { name: 'setup', testMatch: /seeded\/auth\.setup\.ts/ },
    { name: 'seeded', testMatch: /seeded\/.*\.spec\.ts/, dependencies: ['setup'] },
    { name: 'journeys', testMatch: /journeys\/.*\.spec\.ts/, dependencies: ['seeded'] },
    { name: 'integrations', testMatch: /integrations\/.*\.spec\.ts/, dependencies: ['setup'] },
  ],
})
