import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { seededAccounts } from '../helpers/env'
import { api, as } from '../helpers/roles'
import { signIn } from '../helpers/signin'
import { watch } from '../helpers/watch'

/**
 * A route gets its stops (spec section 4): the transportation admin puts
 * three stops on Willow Creek's afternoon route, lets the planner order
 * them and set the times, and applies it. Sam, who drives that route
 * (Bus 12, the only bus with the lift), sees the stops in that order with
 * the children at each; Pat sees when the bus is due at Emma's stop.
 * Turn-by-turn directions need OpenRouteService, which this run doesn't
 * have (tests/integrations/ has them, against a stand-in), so the driver
 * is told why and still has the stop order.
 */
const sam = () => seededAccounts().find((a) => a.email.startsWith('driver.sam'))!
const STOPS = ['Oak St & 3rd Ave', 'Birch Ln Cul-de-sac', 'Pinecrest Apartments']

test("a route's stops are planned, and the driver and family see them", async ({
  page,
  browser,
  baseURL,
}) => {
  const office = await as(browser, 'transportation_admin', baseURL)
  const officeWatch = watch(office)
  await office.goto('/templates')
  const route = office
    .locator('tr', { hasText: 'Willow Creek Elementary' })
    .filter({ has: office.getByRole('cell', { name: 'PM', exact: true }) })
  await expect(route).toContainText('None yet')
  await route.getByRole('button', { name: 'Edit stops' }).click()

  for (const stop of STOPS) {
    await office.getByLabel('Add a stop').selectOption(stop)
    await office.getByRole('button', { name: 'Add to route' }).click()
  }
  await office.getByRole('button', { name: 'Save stops' }).click()
  await expect(route).toContainText(STOPS.join(' → '))

  // The planner orders them and works out the minutes; nothing changes
  // until the plan is applied.
  await route.getByRole('button', { name: 'Edit stops' }).click()
  await office.getByRole('button', { name: 'Plan order and times' }).click()
  const plan = office.locator('.route-plan-result')
  await expect(plan.getByRole('heading', { name: 'Planned route' })).toBeVisible()
  await expect(plan.locator('li')).toHaveCount(3)
  await expect(plan).not.toContainText('Too long for this route')
  expect(await axeViolations(office)).toEqual([])
  await office.getByRole('button', { name: 'Apply this plan' }).click()
  await expect(office.getByRole('button', { name: 'Apply this plan' })).toHaveCount(0)

  // The applied order, and every stop with its minutes from the start.
  const admin = await api('transportation_admin')
  const templates = (await (await admin.get('route-templates')).json()) as {
    school_id: number
    direction: string
    stops: { stop_label: string; minutes_from_start: number | null }[]
  }[]
  const schools = (await (await admin.get('schools')).json()) as { id: number; name: string }[]
  const willow = schools.find((s) => s.name === 'Willow Creek Elementary')!
  const planned = templates.find((t) => t.school_id === willow.id && t.direction === 'pm')!.stops
  expect(planned.map((s) => s.stop_label).sort()).toEqual([...STOPS].sort())
  expect(planned.every((s) => s.minutes_from_start !== null)).toBe(true)
  await admin.dispose()
  await expect(route).toContainText(planned.map((s) => s.stop_label).join(' → '))
  expect(officeWatch.problems()).toEqual([])
  await office.context().close()

  // Sam's afternoon run: the stops in that order, the children at each.
  const watcher = watch(page)
  await signIn(page, sam().email, sam().password)
  const run = page.locator('.driver-run-card', {
    has: page.getByRole('heading', { name: 'Stops in order' }),
  })
  await expect(run.locator('.driver-route-stops li strong')).toHaveText(
    planned.map((s) => s.stop_label),
  )
  await expect(run.locator('li', { hasText: 'Oak St & 3rd Ave' })).toContainText('Emma Ibrahim')
  await expect(run.locator('li', { hasText: 'Birch Ln Cul-de-sac' })).toContainText('Oliver Jensen')
  await expect(run.locator('.driver-stop-time').first()).toHaveText(/^\d\d:\d\d$/)
  await run.getByRole('button', { name: 'Directions' }).click()
  await expect(run.getByText('Turn-by-turn directions need an OpenRouteService key')).toBeVisible()
  expect(await axeViolations(page)).toEqual([])
  expect(watcher.problems()).toEqual([])

  // Pat sees when the afternoon bus is due at Emma's stop.
  const family = await as(browser, 'parent', baseURL)
  await family.goto('/family')
  await expect(
    family.locator('.family-eta', { hasText: 'Bus due at Oak St & 3rd Ave around' }),
  ).toBeVisible()
  await family.context().close()
})
