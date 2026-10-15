import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { expect, type Page } from '@playwright/test'
import { mfaSecretsPath } from './env'
import { nextCode } from './totp'

function savedSecrets(): Record<string, string> {
  return existsSync(mfaSecretsPath())
    ? (JSON.parse(readFileSync(mfaSecretsPath(), 'utf8')) as Record<string, string>)
    : {}
}

function saveSecret(email: string, secret: string) {
  writeFileSync(mfaSecretsPath(), JSON.stringify({ ...savedSecrets(), [email]: secret }, null, 2))
}

/**
 * Signs in through the real sign-in page, as a person would. For a role
 * that needs two-step sign-in, sets it up the first time (reading the
 * setup key off the page, like typing it into an authenticator app) and
 * enters a fresh code after that. Ends on the role's home page.
 */
export async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Email', { exact: true }).fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()

  const home = page.getByRole('button', { name: 'Log out' })
  const setup = page.getByRole('heading', { name: 'Set up two-step sign-in' })
  const verify = page.getByRole('heading', { name: 'Two-step sign-in' })
  await expect(home.or(setup).or(verify)).toBeVisible()

  if (await setup.isVisible()) {
    const secret = (await page.locator('.mfa-secret').innerText()).replace(/\s/g, '')
    saveSecret(email, secret)
    await page.getByLabel('6-digit code').fill(await nextCode(secret))
    await page.getByRole('button', { name: 'Turn on two-step sign-in' }).click()
    await expect(page.getByRole('region', { name: 'Recovery codes' })).toBeVisible()
    await page.getByRole('button', { name: "I've saved them" }).click()
  } else if (await verify.isVisible()) {
    const secret = savedSecrets()[email]
    if (!secret) throw new Error(`${email} has two-step sign-in, but this run never set it up`)
    await page.getByLabel('Code').fill(await nextCode(secret))
    await page.getByRole('button', { name: 'Sign in' }).click()
  }
  await expect(home).toBeVisible()
}
