import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { statePath } from '../helpers/env'
import { as, day } from '../helpers/roles'
import { watch } from '../helpers/watch'

/**
 * A bus goes to the shop on a day it has work: the dispatcher takes it out
 * of service, the schedule says its runs need a bus, a spare is swapped in
 * from the alert, the driver's tablet shows the new bus, and the first bus
 * comes back. (Jordan Rivera drives Bus 07 in the demo district.)
 */
test.use({ storageState: statePath('dispatcher') })

test('a bus in the shop: out of service, a spare swapped in, back in service', async ({
  page,
  browser,
  baseURL,
}) => {
  const watcher = watch(page)

  // Out of service for the whole of today.
  await page.goto('/setup?tab=maintenance')
  await page.getByLabel('Bus', { exact: true }).selectOption({ label: 'Bus 07' })
  await page.getByLabel('Kind').selectOption('repair')
  await page.getByLabel('From', { exact: true }).fill(`${day()}T00:00`)
  await page.getByLabel(/^Until/).fill(`${day(1)}T00:00`)
  await page.getByLabel('Reason').fill('Brake line (e2e)')
  await page.getByRole('button', { name: 'Add maintenance window' }).click()
  await expect(page.getByText(/Maintenance window added/)).toBeVisible()
  const windows = page.getByRole('table', { name: 'Maintenance windows' })
  await expect(windows.getByRole('row', { name: /Bus 07.*Brake line/ })).toBeVisible()

  // Today's schedule: Bus 07's runs need a bus.
  await page.goto('/schedule')
  const alerts = page.locator('.alerts-panel')
  const needsBus = alerts.locator('li', { hasText: 'Needs a bus' })
  await expect(needsBus.first()).toContainText('Bus 07 in maintenance (Brake line (e2e)')
  const lost = await needsBus.count()
  expect(lost).toBeGreaterThan(0)
  expect(await axeViolations(page)).toEqual([])

  // A spare that fits the crew's whole day, swapped in from the alert.
  await needsBus.first().getByRole('button', { name: 'Find a spare bus' }).click()
  await needsBus.first().getByRole('button', { name: 'Swap Van 03 in for Bus 07' }).click()
  await expect(alerts.locator('li', { hasText: 'Needs a bus' })).toHaveCount(0)

  // Jordan's tablet shows the new bus.
  const jordan = await as(browser, 'driver', baseURL)
  await jordan.goto('/driver')
  await expect(jordan.getByText('Vehicle: Van 03').first()).toBeVisible()
  await expect(jordan.getByText('Vehicle: Bus 07')).toHaveCount(0)
  await jordan.context().close()

  // Bus 07 back in service.
  await page.goto('/setup?tab=maintenance')
  await page.getByRole('button', { name: 'Bus 07 back in service' }).click()
  await expect(page.getByText('Bus 07 is back in service.')).toBeVisible()
  expect(watcher.problems()).toEqual([])
})
