import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { API_URL } from '../helpers/env'
import { linkIn, needsMail, waitForMail } from '../helpers/mail'
import { signIn } from '../helpers/signin'
import { watch } from '../helpers/watch'

/**
 * A first-time install, right after docs/deployment.md's steps 1-8
 * (scripts/fresh-install.sh): the server answers safely, and the first
 * administrator can sign in and bring in the first people.
 */

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? ''
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? ''

test.beforeAll(() => {
  if (!ADMIN_EMAIL || !ADMIN_PASSWORD) {
    throw new Error('Set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD (scripts/fresh-install.sh does)')
  }
})

test('the API is up and its documentation is not public', async ({ request }) => {
  const health = await request.get(`${API_URL}/health`)
  expect(health.ok()).toBe(true)
  for (const path of ['/docs', '/redoc', '/openapi.json']) {
    expect((await request.get(`${API_URL}${path}`)).status(), path).toBe(404)
  }
})

test('every response carries the security headers', async ({ request, baseURL }) => {
  for (const url of [`${baseURL}/`, `${API_URL}/health`]) {
    const headers = (await request.get(url)).headers()
    expect(headers['x-content-type-options'], url).toBe('nosniff')
    expect(headers['x-frame-options'], url).toBe('DENY')
    expect(headers['referrer-policy'], url).toBe('strict-origin-when-cross-origin')
    expect(headers['content-security-policy'], url).toContain("frame-ancestors 'none'")
    expect(headers['strict-transport-security'], url).toContain('max-age=')
    expect(headers['server'], url).toBeUndefined()
  }
})

test('nobody gets in without signing in', async ({ request }) => {
  expect((await request.get(`${API_URL}/users/me`)).status()).toBe(401)
  const wrong = await request.post(`${API_URL}/auth/login`, {
    form: { username: ADMIN_EMAIL, password: 'not-the-password' },
  })
  expect(wrong.status()).toBe(401)
})

test('the first administrator sets up two-step sign-in and gets in', async ({ page }) => {
  const watcher = watch(page)
  await signIn(page, ADMIN_EMAIL, ADMIN_PASSWORD)
  await expect(page).toHaveURL(/\/schedule/)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  expect(await axeViolations(page)).toEqual([])
  // The session cookie is the hardened kind.
  const session = (await page.context().cookies()).find((c) => c.httpOnly)
  expect(session?.secure).toBe(true)
  expect(session?.sameSite).toBe('Lax')
  expect(watcher.problems()).toEqual([])
})

test.describe('email', () => {
  needsMail()

  test('a new family gets a set-up email, chooses a password, and can reset it', async ({
    page,
    browser,
    baseURL,
  }) => {
    const email = `family.${Date.now()}@example.org`
    await signIn(page, ADMIN_EMAIL, ADMIN_PASSWORD)
    await page.goto('/users')
    await page.getByLabel('Email', { exact: true }).fill(email)
    await page.getByLabel('Full name').fill('Robin Fresh (test)')
    await page.getByLabel('Role').selectOption('parent')
    await page.getByRole('button', { name: 'Add user' }).click()
    await expect(page.getByText(/has been emailed a link to choose a password/)).toBeVisible()

    // The set-up email, opened in a separate browser like the family's own.
    const setup = await waitForMail(email, /Set up your bus app account/)
    const family = await browser.newContext({ ignoreHTTPSErrors: true, baseURL })
    const familyPage = await family.newPage()
    await familyPage.goto(linkIn(setup.text, 'https://'))
    const first = 'yellow-bus-' + Date.now()
    await familyPage.getByLabel('New password', { exact: true }).fill(first)
    await familyPage.getByLabel('New password again').fill(first)
    await familyPage.getByRole('button', { name: 'Set password' }).click()
    await expect(familyPage.getByRole('status')).toContainText('Your password is set.')
    await signIn(familyPage, email, first)
    await expect(familyPage).toHaveURL(/\/family/)

    // Forgot it: a reset link, a new password, and a notice it changed.
    await familyPage.getByRole('button', { name: 'Log out' }).click()
    await familyPage.getByRole('link', { name: 'Forgot your password?' }).click()
    await familyPage.getByLabel('Email', { exact: true }).fill(email)
    await familyPage.getByRole('button', { name: 'Email me a link' }).click()
    const reset = await waitForMail(email, /Reset your bus app password/)
    await familyPage.goto(linkIn(reset.text, 'https://'))
    const second = 'green-bus-' + Date.now()
    await familyPage.getByLabel('New password', { exact: true }).fill(second)
    await familyPage.getByLabel('New password again').fill(second)
    await familyPage.getByRole('button', { name: 'Set password' }).click()
    await expect(familyPage.getByRole('status')).toContainText('Your password is set.')
    await waitForMail(email, /password was changed/)
    await signIn(familyPage, email, second)
    await family.close()
  })
})
