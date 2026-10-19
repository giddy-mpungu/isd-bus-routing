import { expect, test } from '@playwright/test'
import { statePath } from '../helpers/env'
import { api } from '../helpers/roles'
import { watch } from '../helpers/watch'

/**
 * The nightly roster sync, run by hand: the district's student information
 * system (fakes/oneroster.mjs, OneRoster 1.1 REST behind an OAuth sign-in)
 * lists two new students at Maple Valley; once the school's SIS id is set,
 * "Sync now" brings them in. Needs the harness's --oneroster.
 */
test.use({ storageState: statePath('transportation_admin') })

test('a school mapped to the SIS, "Sync now", and its new students arrive', async ({ page }) => {
  const watcher = watch(page)
  await page.goto('/setup?tab=sis-import')
  await expect(page.getByRole('button', { name: 'Sync now' })).toBeVisible()

  // Students can only land at a school whose SIS id is set.
  await page
    .getByLabel('SIS ID for Maple Valley High School', { exact: true })
    .fill('org-maple-valley')
  await page.getByRole('button', { name: 'Save SIS ID for Maple Valley High School' }).click()
  await expect(page.getByLabel('SIS ID for Maple Valley High School', { exact: true })).toHaveValue(
    'org-maple-valley',
  )

  await page.getByRole('button', { name: 'Sync now' }).click()
  const latest = page.locator('table tbody tr', { hasText: 'Sync now' }).first()
  await expect(latest).toContainText('2 new')

  // They're students of the school now, with their SIS ids and grades.
  const admin = await api('transportation_admin')
  const students = (await (await admin.get('students')).json()) as {
    full_name: string
    external_id: string | null
    grade: string | null
  }[]
  const riley = students.find((s) => s.full_name === 'Riley Synced')
  expect(riley?.external_id).toBe('sis-0001')
  expect(students.some((s) => s.full_name === 'Jamie Rostered')).toBe(true)

  // A second sync changes nothing.
  await page.getByRole('button', { name: 'Sync now' }).click()
  await expect(page.locator('table tbody tr', { hasText: 'Sync now' }).first()).toContainText(
    '0 new',
  )
  await admin.dispose()
  expect(watcher.problems()).toEqual([])
})
