import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { statePath } from '../helpers/env'
import { api, as, day } from '../helpers/roles'
import { watch } from '../helpers/watch'

/**
 * The transportation office brings in the district's bell times, has a
 * route follow them, and re-runs a day the change moved; the school
 * administrator sees their school's bells.
 */
test.use({ storageState: statePath('transportation_admin') })

const CSV = [
  'school,schedule,first_bell,dismissal',
  'Maple Valley High School,Regular,07:30,14:50',
  'Cedar Ridge Middle School,Regular,07:40,14:55',
  'Willow Creek Elementary,Regular,08:00,15:00',
  'Willow Creek Elementary,Early release,08:00,12:00',
  'Nowhere Academy,Regular,08:00,15:00',
].join('\n')

test('bell times imported, a route following them, the school admin sees them', async ({
  page,
  browser,
  baseURL,
}) => {
  const watcher = watch(page)

  // The district's bell list: previewed (one row refused), then imported.
  await page.goto('/setup?tab=bells')
  await page.getByLabel('Or paste it').fill(CSV)
  await page.getByRole('button', { name: 'Preview' }).click()
  const preview = page.getByRole('table', { name: 'Preview: nothing saved yet' })
  await expect(
    preview.getByRole('row', { name: /Nowhere Academy.*No school by that name/ }),
  ).toBeVisible()
  await expect(preview.getByRole('row', { name: /created/ })).toHaveCount(4)
  await page.getByRole('button', { name: 'Import these bell times' }).click()
  await expect(page.getByRole('table', { name: 'Imported' })).toBeVisible()
  await page.getByLabel('Show the bells of').selectOption({ label: 'Willow Creek Elementary' })
  const bells = page.getByRole('table', { name: 'Bell schedules at Willow Creek Elementary' })
  await expect(bells.getByRole('row', { name: /Regular.*08:00.*15:00/ })).toBeVisible()
  expect(await axeViolations(page)).toEqual([])

  // Willow Creek's morning route follows its bells from now on.
  await page.goto('/templates')
  const route = page
    .locator('.route-templates-section tbody tr')
    .filter({ hasText: 'Willow Creek Elementary' })
    .filter({ hasText: 'AM' })
  await route.getByRole('button', { name: 'Follow bells' }).click()
  await expect(route.getByText('Follows bells')).toBeVisible()
  // 08:00 first bell, arriving 10-25 minutes before, 35+5 minutes on the road.
  await expect(route).toContainText('06:55–07:50')

  // Runs already made for the days ahead moved with it...
  const admin = await api('transportation_admin')
  const schools = (await (await admin.get('schools')).json()) as { id: number; name: string }[]
  const willow = schools.find((s) => s.name === 'Willow Creek Elementary')!
  const runs = (await (await admin.get(`runs?service_date=${day(3)}`)).json()) as {
    school_id: number
    direction: string
    window_earliest: number
    window_latest: number
  }[]
  const am = runs.find((r) => r.school_id === willow.id && r.direction === 'am')!
  expect([am.window_earliest, am.window_latest]).toEqual([415, 470])
  await admin.dispose()

  // ...and once the schedule is run again for that day, nothing is left
  // outside its window.
  await page.goto('/schedule')
  await page.getByLabel('Service date').fill(day(3))
  await page.getByRole('button', { name: 'Run schedule' }).click()
  await expect(page.getByText(/^Schedule solved using \d+ crew/)).toBeVisible()
  await expect(
    page.locator('.alerts-panel li', { hasText: 'no longer fits its window' }),
  ).toHaveCount(0)
  expect(watcher.problems()).toEqual([])

  // The school administrator sees the bells, read-only.
  const principal = await as(browser, 'school_admin', baseURL)
  await principal.goto('/school')
  const panel = principal.locator('.school-bells')
  await expect(panel).toContainText('Regular: first bell 08:00, dismissal 15:00 (regular)')
  await expect(panel).toContainText('Early release: first bell 08:00, dismissal 12:00')
  await expect(principal.getByRole('button', { name: /Edit/ })).toHaveCount(0)
  expect(await axeViolations(principal)).toEqual([])
  await principal.context().close()
})
