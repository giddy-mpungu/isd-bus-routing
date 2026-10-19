import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { statePath } from '../helpers/env'
import { day } from '../helpers/roles'
import { watch } from '../helpers/watch'

/**
 * A driver calls in sick for a day ahead (Taylor Brooks, Bus 19): the
 * schedule flags the runs that need cover, ranks substitutes, and the
 * spare driver takes over Taylor's bus and runs.
 */
test.use({ storageState: statePath('dispatcher') })

test('a sick day: needs cover, a substitute ranked and assigned', async ({ page }) => {
  const watcher = watch(page)
  await page.goto('/schedule')
  await page.getByLabel('Service date').fill(day(5))
  await expect(page.getByRole('heading', { name: `Runs for ${day(5)}` })).toBeVisible()

  await page.getByLabel('Absent driver').selectOption({ label: 'Taylor Brooks' })
  await page.getByLabel('Reason', { exact: true }).selectOption('sick_leave')
  await page.getByRole('button', { name: 'Report absence' }).click()
  const absence = page.locator('li', { hasText: 'Taylor Brooks — sick leave' })
  await expect(absence).toBeVisible()

  const needsCover = page.locator('.alerts-panel li', { hasText: 'Needs cover' })
  await expect(needsCover.first()).toContainText('on Bus 19')
  await expect(needsCover.first()).toContainText('driver absent (sick leave')
  expect(await needsCover.count()).toBeGreaterThan(0)

  // The spare driver, ranked, takes over.
  await absence.getByRole('button', { name: 'Find substitutes' }).click()
  const results = page.locator('.substitute-results')
  await expect(
    results.getByRole('heading', { name: 'Substitutes for Taylor Brooks' }),
  ).toBeVisible()
  const casey = results.locator('li', { hasText: 'Casey Morgan' }).first()
  await expect(casey).toBeVisible()
  expect(await axeViolations(page)).toEqual([])
  await casey.getByRole('button', { name: 'Assign as substitute' }).click()
  await expect(page.locator('.alerts-panel li', { hasText: 'Needs cover' })).toHaveCount(0)
  expect(watcher.problems()).toEqual([])
})
