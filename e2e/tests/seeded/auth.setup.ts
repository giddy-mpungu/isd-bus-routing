import { test as setup } from '@playwright/test'
import { seededAccounts, statePath, type Role } from '../helpers/env'
import { signIn } from '../helpers/signin'

/**
 * Signs in once as each role of the seeded demo district, through the real
 * sign-in page (setting up two-step sign-in for the roles that need it),
 * and saves each session for the tests that follow.
 */
const roles = [...new Set(seededAccounts().map((a) => a.role))] as Role[]

for (const role of roles) {
  setup(`sign in as ${role}`, async ({ page }) => {
    const login = seededAccounts().find((a) => a.role === role)!
    await signIn(page, login.email, login.password)
    await page.context().storageState({ path: statePath(role) })
  })
}
