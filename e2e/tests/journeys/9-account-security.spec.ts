import { randomBytes } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'
import { MAILPIT_URL } from '../helpers/env'
import { waitForMail } from '../helpers/mail'
import { api, as } from '../helpers/roles'
import { finishSignIn, mfaSecretFor, signIn } from '../helpers/signin'
import { nextCode } from '../helpers/totp'
import { watch } from '../helpers/watch'

/**
 * A new dispatcher's account, start to lost phone: they set up two-step
 * sign-in, keep recovery codes, change their password (the old one stops
 * working), sign in with a recovery code (once only), and when the phone
 * is gone a transportation admin resets two-step sign-in, which signs them
 * out and has them set it up again. A fresh account, so the seeded logins
 * the other tests use stay as they were.
 */
const email = `casey.newstaff.${Date.now()}@demo.example.org`
// Made up fresh each run, never written down anywhere.
const fresh = () => randomBytes(16).toString('hex')
const [firstPassword, secondPassword] = [fresh(), fresh()]

async function passwordStep(page: Page, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email', { exact: true }).fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test('a dispatcher keeps their account safe, and gets back in after losing their phone', async ({
  browser,
  baseURL,
}) => {
  test.slow() // each authenticator code waits for a fresh 30-second step
  const admin = await api('transportation_admin')
  const created = await admin.post('users', {
    data: { email, full_name: 'Casey Newstaff', role: 'dispatcher', password: firstPassword },
  })
  expect(created.ok(), await created.text()).toBe(true)
  await admin.dispose()

  const context = await browser.newContext({ baseURL, ignoreHTTPSErrors: true })
  const page = await context.newPage()
  const watcher = watch(page)

  // First sign-in: two-step sign-in is set up (a dispatcher must have it).
  await signIn(page, email, firstPassword)

  // A fresh set of recovery codes, kept somewhere safe.
  await page.goto('/account')
  await page
    .getByLabel('Code from your app, to make new recovery codes')
    .fill(await nextCode(mfaSecretFor(email)))
  await page.getByRole('button', { name: 'Make new recovery codes' }).click()
  const codesRegion = page.getByRole('region', { name: 'Recovery codes' })
  await expect(codesRegion).toBeVisible()
  const codes = await codesRegion.locator('code').allInnerTexts()
  expect(codes.length).toBeGreaterThan(3)
  await page.getByRole('button', { name: "I've saved them" }).click()

  // A new password.
  await page.getByLabel('Current password').fill(firstPassword)
  await page.getByLabel('New password', { exact: true }).fill(secondPassword)
  await page.getByLabel('New password again').fill(secondPassword)
  await page.getByRole('button', { name: 'Change password' }).click()
  await expect(page.getByRole('status')).toContainText('Password changed')
  if (MAILPIT_URL) await waitForMail(email, /Your bus app password was changed/)
  await page.getByRole('button', { name: 'Log out' }).click()

  // The old password no longer gets in.
  await passwordStep(page, firstPassword)
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Two-step sign-in' })).toBeHidden()

  // The new one does; a recovery code stands in for the phone, once.
  await passwordStep(page, secondPassword)
  await expect(page.getByRole('heading', { name: 'Two-step sign-in' })).toBeVisible()
  await page.getByLabel('Code').fill(codes[0])
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('button', { name: 'Log out' })).toBeVisible()
  await page.goto('/account')
  await expect(page.getByText(`You have ${codes.length - 1} recovery codes left`)).toBeVisible()
  await page.getByRole('button', { name: 'Log out' }).click()

  await passwordStep(page, secondPassword)
  await page.getByLabel('Code').fill(codes[0])
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Log out' })).toBeHidden()

  // Phone lost and no codes to hand: the transportation office resets it.
  await passwordStep(page, secondPassword) // (signed in once more, on their laptop)
  await finishSignIn(page, email)
  const office = await as(browser, 'transportation_admin', baseURL)
  await office.goto('/users')
  const row = office.getByRole('row').filter({ hasText: email })
  await expect(row).toContainText('2-step on')
  office.once('dialog', (dialog) => void dialog.accept())
  await row.getByRole('button', { name: 'Reset 2-step' }).click()
  await expect(row).not.toContainText('2-step on')
  if (MAILPIT_URL) await waitForMail(email, /Your bus app two-step sign-in was reset/)
  await office.context().close()

  // That signed them out everywhere; at the next sign-in they set it up again.
  await page.reload()
  await expect(page.getByLabel('Password', { exact: true })).toBeVisible()
  await passwordStep(page, secondPassword)
  await expect(page.getByRole('heading', { name: 'Set up two-step sign-in' })).toBeVisible()
  await finishSignIn(page, email)

  expect(watcher.problems()).toEqual([])
  await context.close()
})
