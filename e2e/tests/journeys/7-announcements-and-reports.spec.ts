import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { statePath } from '../helpers/env'
import { as, day } from '../helpers/roles'

/**
 * An announcement reaches exactly the people it's for, and the reports
 * download as files a spreadsheet opens.
 */
test.use({ storageState: statePath('dispatcher') })

test("a Willow Creek families' notice reaches their families, not drivers or other schools", async ({
  page,
  browser,
  baseURL,
}) => {
  const message = `Willow Creek pickup moves to the north loop tomorrow (e2e ${Date.now()})`
  await page.goto('/setup?tab=announcements')
  await page.getByLabel('Message').fill(message)
  await page.getByLabel('Announcement category').selectOption('route_change')
  await page.getByLabel('Audience').selectOption('family')
  await page.getByLabel(/^School \(optional/).selectOption({ label: 'Willow Creek Elementary' })
  await page.getByRole('button', { name: 'Post announcement' }).click()
  await expect(page.getByText(message)).toBeVisible()

  // Pat's Emma goes to Willow Creek: Pat sees it.
  const parent = await as(browser, 'parent', baseURL)
  await parent.goto('/family')
  await expect(parent.getByText(message)).toBeVisible()
  await parent.context().close()

  // Noah goes to Maple Valley, and drivers aren't the audience.
  for (const role of ['student', 'driver'] as const) {
    const other = await as(browser, role, baseURL)
    await other.goto(role === 'driver' ? '/driver' : '/family')
    await expect(other.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(other.getByText(message)).toHaveCount(0)
    await other.context().close()
  }

  // Willow Creek's principal sees notices for their school.
  const principal = await as(browser, 'school_admin', baseURL)
  await principal.goto('/school')
  await expect(principal.getByText(message)).toBeVisible()
  await principal.context().close()
})

test('every report previews and downloads as CSV', async ({ page }) => {
  await page.goto('/reports')
  const reports = [
    'Assignments and on-time performance',
    'Field trips',
    'Driver absences and cover',
    'Incident and vehicle defect reports',
    'Dispatch tasks',
    'GPS position history',
  ]
  for (const label of reports) {
    await page.getByLabel('Report', { exact: true }).selectOption({ label })
    await page.getByLabel('From', { exact: true }).fill(day())
    await page.getByLabel('To', { exact: true }).fill(day(5))
    await page.getByRole('button', { name: /^Show/ }).click()
    const link = page.getByRole('link', { name: /^Download CSV/ })
    await expect(link).toBeVisible()
    const download = page.waitForEvent('download')
    await link.click()
    const csv = readFileSync(await (await download).path(), 'utf8')
    expect(csv.split('\n')[0], label).toContain(',')
  }
})
