import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { statePath, type Role } from '../helpers/env'
import { watch } from '../helpers/watch'

/**
 * Every page each role can open loads without errors and meets WCAG 2.1
 * AA, contrast included, on the seeded demo district.
 */

const STAFF_TABS = [
  'schools',
  'fleet',
  'bells',
  'maintenance',
  'district-knowledge',
  'announcements',
  'optimization',
]
const ADMIN_TABS = [...STAFF_TABS, 'sis-import', 'corrections', 'audit-log']

const PAGES: Record<Role, string[]> = {
  transportation_admin: [
    '/schedule',
    '/field-trips',
    '/templates',
    '/reports',
    ...ADMIN_TABS.map((tab) => `/setup?tab=${tab}`),
    '/users',
    '/account',
  ],
  dispatcher: [
    '/schedule',
    '/field-trips',
    '/templates',
    '/reports',
    ...STAFF_TABS.map((tab) => `/setup?tab=${tab}`),
    '/account',
  ],
  school_admin: ['/school', '/account'],
  driver: ['/driver', '/account'],
  parent: ['/family', '/account'],
  student: ['/family', '/account'],
}

for (const [role, paths] of Object.entries(PAGES) as [Role, string[]][]) {
  test.describe(role, () => {
    test.use({ storageState: statePath(role) })

    for (const path of paths) {
      test(`${path} loads cleanly and is accessible`, async ({ page }) => {
        const watcher = watch(page)
        await page.goto(path)
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
        await page.waitForLoadState('networkidle')
        // No error messages on the page.
        await expect(page.locator('[role="alert"].error')).toHaveCount(0)
        expect(await axeViolations(page)).toEqual([])
        expect(watcher.problems()).toEqual([])
      })
    }
  })
}

test.describe('in Spanish', () => {
  for (const [role, path] of [
    ['parent', '/family'],
    ['driver', '/driver'],
  ] as [Role, string][]) {
    test.describe(role, () => {
      test.use({ storageState: statePath(role) })

      test(`${path} in Spanish is accessible and marked as Spanish`, async ({ page }) => {
        const watcher = watch(page)
        await page.goto(path)
        await page.getByLabel('Language').selectOption('es')
        await expect(page.locator('html')).toHaveAttribute('lang', 'es')
        await expect(page.getByRole('button', { name: 'Cerrar sesión' })).toBeVisible()
        await page.waitForLoadState('networkidle')
        expect(await axeViolations(page)).toEqual([])
        // Back to English for the other tests (the choice is saved to the account).
        await page.getByLabel('Idioma').selectOption('en')
        await expect(page.getByRole('button', { name: 'Log out' })).toBeVisible()
        expect(watcher.problems()).toEqual([])
      })
    })
  }
})
