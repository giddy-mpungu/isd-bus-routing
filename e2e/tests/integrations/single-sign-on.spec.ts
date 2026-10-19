import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { finishSignIn } from '../helpers/signin'

/**
 * Single sign-on with the district's identity provider (a local Keycloak,
 * dev/keycloak/make_realm.py): staff and drivers with an account here sign
 * in with their district login; nobody gets in without an account here;
 * the provider's sign-in doesn't stand in for this system's two-step check
 * unless the provider says it did one. Needs E2E_SSO_USERS (the realm's
 * users.txt) and the api's OIDC settings (harness --api-env).
 */
const USERS = process.env.E2E_SSO_USERS ?? ''

function password(email: string): string {
  const line = readFileSync(USERS, 'utf8')
    .split(/\r?\n/)
    .find((l) => l.startsWith(`${email} `))
  if (!line) throw new Error(`${email} isn't in ${USERS}`)
  return line.trim().split(/\s+/)[1]
}

async function districtSignIn(page: Page, email: string) {
  await page.goto('/login')
  await page.getByRole('link', { name: /^Sign in with/ }).click()
  // The provider's own page.
  await page.locator('#username').fill(email)
  await page.locator('#password').fill(password(email))
  await page.locator('#kc-login').click()
}

test.describe('single sign-on', () => {
  test.skip(!USERS, 'No identity provider in this run (E2E_SSO_USERS unset)')

  test('a driver signs in with their district account', async ({ page }) => {
    await districtSignIn(page, 'driver.jordan@demo.example.org')
    await expect(page).toHaveURL(/\/driver/)
    await expect(page.getByRole('heading', { name: /^My day/ })).toBeVisible()
  })

  test("a dispatcher still passes this system's two-step check (the provider reported none)", async ({
    page,
  }) => {
    await districtSignIn(page, 'dispatcher@demo.example.org')
    // Set up already (seeded/auth.setup.ts), so it asks for a code.
    await expect(
      page
        .getByRole('heading', { name: 'Two-step sign-in' })
        .or(page.getByRole('heading', { name: 'Set up two-step sign-in' })),
    ).toBeVisible()
    await finishSignIn(page, 'dispatcher@demo.example.org')
    await expect(page).toHaveURL(/\/schedule/)
  })

  test("someone the district knows but this system doesn't is turned away", async ({ page }) => {
    await districtSignIn(page, 'not.in.app@demo.example.org')
    await expect(page).toHaveURL(/\/login\?sso_error=no_account/)
    await expect(page.getByRole('alert')).toContainText(
      "There's no account for that district email here",
    )
  })
})
