import { expect, test } from '@playwright/test'
import { mapRequests, needsMaps } from '../helpers/maps'
import { statePath } from '../helpers/env'
import { watch } from '../helpers/watch'

/**
 * A student's home address looked up with the US Census geocoder (here the
 * stand-in, fakes/maps.mjs): a known address is matched and placed; one
 * it doesn't know asks for a pin on the map instead. Only the address
 * leaves the system, never the child's name. Needs the harness's --maps.
 */
needsMaps()
test.use({ storageState: statePath('transportation_admin') })

test('a home address is looked up, and only the address is sent', async ({ page }) => {
  const watcher = watch(page)
  await page.goto('/setup?tab=schools')
  const emma = page.locator('li', { hasText: 'Emma Ibrahim' }).first()
  await emma.getByRole('button', { name: 'Home', exact: true }).click()

  // An address the Census doesn't know: say so, and offer the map.
  await emma.getByLabel('Home address').fill('999 Nowhere Rd, Houston, TX 77007')
  await emma.getByRole('button', { name: 'Look up with Census' }).click()
  await expect(emma.getByRole('alert')).toContainText("couldn't find that address")

  // One it knows.
  await emma.getByLabel('Home address').fill('100 Test Lane, Houston, TX 77007')
  await emma.getByRole('button', { name: 'Look up with Census' }).click()
  await expect(emma.getByText('Census match: 100 TEST LN, HOUSTON, TX, 77007')).toBeVisible()

  // What went out: the address and the lookup's own settings, nothing else.
  const census = (await mapRequests()).filter((r) => r.service === 'census')
  expect(census.map((r) => r.query?.address)).toEqual([
    '999 Nowhere Rd, Houston, TX 77007',
    '100 Test Lane, Houston, TX 77007',
  ])
  for (const request of census)
    expect(Object.keys(request.query ?? {}).sort()).toEqual(['address', 'benchmark', 'format'])
  expect(JSON.stringify(census)).not.toContain('Emma')

  // A 422 from the lookup is the expected "not found", not a failure.
  expect(watcher.problems()).toEqual([])
})
