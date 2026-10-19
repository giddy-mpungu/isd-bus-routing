import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { seededAccounts } from '../helpers/env'
import { as } from '../helpers/roles'
import { signIn } from '../helpers/signin'
import { watch } from '../helpers/watch'

/**
 * A driver's day on the tablet (Sam Okafor, Bus 12 with the lift): a run
 * from acknowledged to completed, the riders by stop, a defect report
 * that dispatch then sees and closes, and a late-evening absence.
 */
const sam = () => seededAccounts().find((a) => a.email.startsWith('driver.sam'))!

test('a driver works a run start to finish and reports a defect', async ({
  page,
  browser,
  baseURL,
}) => {
  const watcher = watch(page)
  await signIn(page, sam().email, sam().password)
  await expect(page).toHaveURL(/\/driver/)

  // The first run of the day, one big button at a time.
  // Pinned by its time: cards move between Current, Next and Done as work goes on.
  const runs = page.locator('.driver-run-card:not(.driver-task-card):not(.driver-trip-card)')
  const time = await runs.first().locator('.driver-run-time').innerText()
  const run = runs.filter({ hasText: time })
  await expect(run.getByText('Vehicle: Bus 12 (lift)')).toBeVisible()
  const steps: [string, string][] = [
    ['Acknowledge', 'Acknowledged'],
    ["I'm en route", 'En route'],
    ['Arrived', 'Arrived'],
    ['Start run', 'In progress'],
    ['Complete run', 'Completed'],
  ]
  for (const [button, status] of steps) {
    await run.getByRole('button', { name: button, exact: true }).click()
    await expect(run.locator('.driver-run-status')).toContainText(status)
  }
  await expect(run.getByRole('button', { name: 'No-show' })).toHaveCount(0)
  expect(await axeViolations(page)).toEqual([])

  // A defect report, from the bus the driver is on.
  await page.getByLabel('Type').selectOption('vehicle_defect')
  await page.getByLabel('Description').fill('Wheelchair lift is slow to fold (e2e)')
  await page.getByRole('button', { name: 'Submit report' }).click()
  await expect(page.getByText('Report submitted.')).toBeVisible()

  // An absence late tonight, after the day's work.
  await page.getByLabel('Reason').selectOption('personal_day')
  await page.getByLabel('Whole day').uncheck()
  await page.getByLabel('Start (minute of day)').fill('1380')
  await page.getByLabel('End (minute of day)').fill('1439')
  await page.getByRole('button', { name: 'Report absence' }).click()
  await expect(page.getByText('Absence reported.')).toBeVisible()
  expect(watcher.problems()).toEqual([])

  // Dispatch sees the defect, among the alerts and in Maintenance, and closes it.
  const dispatch = await as(browser, 'dispatcher', baseURL)
  await dispatch.goto('/schedule')
  await expect(
    dispatch.locator('.alerts-panel li', { hasText: 'Wheelchair lift is slow to fold' }),
  ).toContainText('Vehicle defect reported by Sam Okafor')
  await dispatch.goto('/setup?tab=maintenance')
  const report = dispatch.locator('.defect-list li', { hasText: 'Wheelchair lift is slow to fold' })
  await expect(report).toContainText('Bus 12 (lift)')
  await report.getByRole('button', { name: /^Mark report \d+ fixed$/ }).click()
  await report.getByLabel('What was done (optional)').fill('Hydraulics adjusted')
  await report.getByRole('button', { name: 'Mark fixed' }).click()
  await expect(dispatch.getByText('Marked fixed.')).toBeVisible()
  await expect(report).toHaveCount(0)
  await dispatch.goto('/schedule')
  await expect(
    dispatch.locator('.alerts-panel li', { hasText: 'Wheelchair lift is slow to fold' }),
  ).toHaveCount(0)
  await dispatch.context().close()
})
