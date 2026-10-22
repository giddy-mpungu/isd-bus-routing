import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { seededAccounts } from '../helpers/env'
import { api, as } from '../helpers/roles'
import { signIn } from '../helpers/signin'
import { watch } from '../helpers/watch'

/**
 * A route's stops change (spec section 4): the demo district starts with
 * every route planned; the transportation admin trims Willow Creek's
 * afternoon route to three stops, lets the planner order them and set the
 * times, and applies it. Sam, who drives that route
 * (Bus 12, the only bus with the lift), sees the stops in that order with
 * the children at each; Pat sees when the bus is due at Emma's stop.
 * Turn-by-turn directions come from the district's routing engine: the
 * fresh install's stack runs the real one (E2E_ROUTING_ENGINE=1) with the
 * demo district's map, so Sam gets them; a run without it tells the driver
 * why, and the stop order is still there.
 */
const sam = () => seededAccounts().find((a) => a.email.startsWith('driver.sam'))!
const STOPS = ['Oak St & 3rd Ave', 'Birch Ln Cul-de-sac', 'Pinecrest Apartments']
const DROPPED = ['Riverside Park Entrance', 'Hillcrest Community Center']

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
  // Planned when the demo district was loaded: every stop its children use.
  for (const stop of [...STOPS, ...DROPPED]) await expect(route).toContainText(stop)
  await route.getByRole('button', { name: 'Edit stops' }).click()

  for (const stop of DROPPED) {
    await office.getByRole('button', { name: `Remove ${stop}` }).click()
  }
  await office.getByRole('button', { name: 'Save stops' }).click()
  for (const stop of DROPPED) await expect(route).not.toContainText(stop)

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
  // The morning run keeps all its planned stops; the afternoon one is the
  // route just trimmed.
  const run = page.locator('.driver-run-card', {
    has: page.getByRole('heading', { name: 'Stops in order' }),
    hasNot: page.locator('.driver-route-stops strong', { hasText: DROPPED[0] }),
  })
  await expect(run.locator('.driver-route-stops li strong')).toHaveText(
    planned.map((s) => s.stop_label),
  )
  await expect(run.locator('li', { hasText: 'Oak St & 3rd Ave' })).toContainText('Emma Ibrahim')
  await expect(run.locator('li', { hasText: 'Birch Ln Cul-de-sac' })).toContainText('Oliver Jensen')
  await expect(run.locator('.driver-stop-time').first()).toHaveText(/^\d\d:\d\d$/)
  await run.getByRole('button', { name: 'Directions' }).click()
  if (process.env.E2E_ROUTING_ENGINE) {
    await expect(run.locator('.directions-steps li').first()).toBeVisible()
  } else {
    await expect(run.getByText('Turn-by-turn directions need')).toBeVisible()
  }
  expect(await axeViolations(page)).toEqual([])
  expect(watcher.problems()).toEqual([])

  // Pat sees when the afternoon bus is due at Emma's stop.
  const family = await as(browser, 'parent', baseURL)
  await family.goto('/family')
  await expect(
    // Emma's afternoon bus is the lift bus, between 14:40 and 15:35.
    family.locator('.family-eta', {
      hasText: /Bus due at Oak St & 3rd Ave around 1[45]:\d\d\. Bus 12 \(lift\)/,
    }),
  ).toBeVisible()
  await family.context().close()
})
