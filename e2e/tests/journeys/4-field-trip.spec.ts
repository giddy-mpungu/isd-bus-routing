import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { statePath } from '../helpers/env'
import { api, day } from '../helpers/roles'
import { watch } from '../helpers/watch'

/**
 * The demo district's waiting field trip (in two days, 09:00-13:30): the
 * dispatcher checks a driver and bus for conflicts, sees a bus too small
 * for the class refused, and assigns a pair that's free and big enough.
 */
test.use({ storageState: statePath('dispatcher') })

test('a field trip checked for conflicts and assigned', async ({ page }) => {
  const watcher = watch(page)
  await page.goto('/field-trips')
  await page.getByLabel('Departure date').fill(day(2))
  const trip = page.locator('li', { hasText: 'Gulf Coast Science Museum' }).first()
  await expect(trip).toBeVisible()

  // A van is too small for 38 students: refused, and Assign stays off.
  await trip.getByLabel('Candidate driver').selectOption({ label: 'Casey Morgan' })
  await trip.getByLabel('Candidate vehicle').selectOption({ label: 'Van 03' })
  await trip.getByRole('button', { name: 'Check conflicts' }).click()
  await expect(trip.locator('.field-trip-conflicts')).toContainText(
    'Vehicle Van 03 carries 12; this trip has 38 passengers',
  )
  await expect(trip.getByRole('button', { name: 'Assign' })).toBeDisabled()

  // The spare driver on a big bus that's free between its runs.
  await trip.getByLabel('Candidate vehicle').selectOption({ label: 'Bus 19' })
  await trip.getByRole('button', { name: 'Check conflicts' }).click()
  await expect(trip.getByText('No conflicts.')).toBeVisible()
  expect(await axeViolations(page)).toEqual([])
  await trip.getByRole('button', { name: 'Assign' }).click()

  // Recorded on the trip.
  const dispatcher = await api('dispatcher')
  await expect
    .poll(async () => {
      const trips = (await (await dispatcher.get('field-trips')).json()) as {
        destination: string
        assigned_driver_id: number | null
        assigned_vehicle_id: number | null
        status: string
      }[]
      const museum = trips.find((t) => t.destination === 'Gulf Coast Science Museum')
      return museum ? [museum.assigned_driver_id !== null, museum.assigned_vehicle_id !== null] : []
    })
    .toEqual([true, true])
  await dispatcher.dispose()
  expect(watcher.problems()).toEqual([])
})
