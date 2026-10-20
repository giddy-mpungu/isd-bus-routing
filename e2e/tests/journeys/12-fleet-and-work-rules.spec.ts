import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { statePath } from '../helpers/env'
import { api } from '../helpers/roles'
import { watch } from '../helpers/watch'

/**
 * The transportation office records what a bus is (spec section 6: its
 * type and wheelchair positions) and the district's driver work-hour rules
 * (section 2.1), which stay off until someone sets them. Bus 12 carries
 * the lift in the demo district; Willow Creek's runs need it.
 */
test.use({ storageState: statePath('transportation_admin') })

// Whatever happens, the rules end up off again, so the journeys after this
// one plan their days as before.
test.afterEach(async () => {
  const admin = await api('transportation_admin')
  const current = (await (await admin.get('optimization-settings')).json()) as Record<
    string,
    unknown
  >
  delete current.is_default
  await admin.put('optimization-settings', {
    data: {
      ...current,
      max_duty_minutes: null,
      break_after_minutes: null,
      break_minutes: null,
      min_rest_minutes: null,
    },
  })
  await admin.dispose()
})

test('Bus 12 gets its type and wheelchair positions; work-hour rules set and cleared', async ({
  page,
}) => {
  const watcher = watch(page)

  await page.goto('/setup?tab=fleet')
  const bus = page.locator('.vehicles-section li', { hasText: 'Bus 12' }).first()
  await bus.getByRole('button', { name: 'Edit' }).click()
  await page.getByLabel('Vehicle type', { exact: true }).selectOption('type_c')
  await page.getByLabel('Wheelchair positions', { exact: true }).fill('2')
  await page.getByLabel('Turning radius (m)', { exact: true }).fill('12.5')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  const saved = page.locator('.vehicles-section li', { hasText: 'Bus 12' }).first()
  await expect(saved).toContainText('Type C (conventional)')
  await expect(saved).toContainText('2 wheelchair positions')
  await expect(saved).toContainText('turns in 12.5m')
  expect(await axeViolations(page)).toEqual([])

  // Work-hour rules: off by default.
  await page.goto('/setup?tab=optimization')
  const duty = page.getByLabel('Longest day on duty (hours)')
  await expect(duty).toHaveValue('')
  await duty.fill('10')
  await page.getByLabel('Most work before a break (hours)').fill('4')
  await page.getByLabel('Shortest break (minutes)').fill('30')
  await page.getByRole('button', { name: 'Save settings' }).click()
  await expect(page.getByText(/apply the next time a schedule is solved/)).toBeVisible()
  expect(await axeViolations(page)).toEqual([])

  const admin = await api('transportation_admin')
  const settings = (await (await admin.get('optimization-settings')).json()) as Record<
    string,
    number | null
  >
  expect([settings.max_duty_minutes, settings.break_after_minutes, settings.break_minutes]).toEqual(
    [600, 240, 30],
  )

  // A break needs both its numbers.
  await page.getByLabel('Shortest break (minutes)').fill('')
  await page.getByRole('button', { name: 'Save settings' }).click()
  await expect(page.getByRole('alert')).toContainText('break')

  // Cleared again, so later tests plan as before.
  await duty.fill('')
  await page.getByLabel('Most work before a break (hours)').fill('')
  await page.getByRole('button', { name: 'Save settings' }).click()
  await expect(page.getByText(/apply the next time a schedule is solved/)).toBeVisible()
  const cleared = (await (await admin.get('optimization-settings')).json()) as Record<
    string,
    number | null
  >
  expect(cleared.max_duty_minutes).toBeNull()
  expect(cleared.break_after_minutes).toBeNull()
  await admin.dispose()
  expect(watcher.problems()).toEqual([])
})
