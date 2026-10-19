import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { api, as } from '../helpers/roles'
import { watch } from '../helpers/watch'

/**
 * New families at Willow Creek and nowhere for them to catch the bus
 * (spec section 3): their homes go on file, one placed by hand on the map,
 * and "Propose stops" suggests where. Two neighbours far from any stop
 * get a new one together, moved a little on the map before it's approved;
 * a child near Elm St is given that existing stop; a child next to school
 * (riding only because of a hazardous walk) has their proposal turned
 * down. Fictional children and homes; no address goes to the Census here.
 */
test('homes on file, stops proposed, moved, approved and turned down', async ({
  browser,
  baseURL,
}) => {
  const admin = await api('transportation_admin')
  const ok = async (response: Promise<import('@playwright/test').APIResponse>) => {
    const r = await response
    expect(r.ok(), `${r.url()}: ${await r.text()}`).toBe(true)
    return r.json()
  }
  const schools = (await ok(admin.get('schools'))) as { id: number; name: string }[]
  const willow = schools.find((s) => s.name === 'Willow Creek Elementary')!
  const stops = (await ok(admin.get('stops'))) as { id: number; label: string }[]
  const elm = stops.find((s) => s.label === 'Elm St & Maple Dr')!

  const newStudent = (full_name: string, extra: object = {}) =>
    ok(admin.post('students', { data: { full_name, school_id: willow.id, grade: '3', ...extra } }))
  const harper = (await newStudent('Harper Newhome', { hazardous_route: true })) as { id: number }
  const rowan = (await newStudent('Rowan Farfield')) as { id: number }
  const quinn = (await newStudent('Quinn Farfield')) as { id: number }
  const kai = (await newStudent('Kai Elmwood')) as { id: number }
  // More than 2 miles from school, so bus-eligible: the Farfields next door
  // to each other, far from any stop; Kai a few steps from Elm St.
  for (const [student, address, lat, lon] of [
    [rowan, '1 Farfield Ct (e2e)', 29.74, -95.4],
    [quinn, '3 Farfield Ct (e2e)', 29.7403, -95.4003],
    [kai, '20 Elm St (e2e)', 29.7447, -95.3762],
  ] as const) {
    await ok(
      admin.put(`students/${student.id}/home`, {
        data: { address, location_lat: lat, location_lon: lon },
      }),
    )
  }

  const page = await as(browser, 'transportation_admin', baseURL)
  const watcher = watch(page)
  await page.goto('/setup?tab=schools')

  // Harper's home, placed by hand (the map's own button, as from a keyboard).
  const harperRow = page.locator('li', { hasText: 'Harper Newhome' }).first()
  await harperRow.getByRole('button', { name: 'Home', exact: true }).click()
  await harperRow.getByLabel('Home address').fill('12 Schoolside Way (e2e)')
  await harperRow.getByRole('button', { name: 'Place it at the centre of the map' }).click()
  await harperRow.getByRole('button', { name: 'Save the placed spot' }).click()
  await expect(harperRow.getByText('Placed by hand on the map.')).toBeVisible()

  // Proposals for the school.
  await page.locator('#proposals-school').selectOption(String(willow.id))
  await page.getByRole('button', { name: 'Propose stops' }).click()
  await expect(page.getByText('3 proposal(s) for 4 student(s).')).toBeVisible()
  const proposals = page.locator('.stop-proposals-list > li')
  const together = proposals.filter({ hasText: 'Rowan Farfield' })
  await expect(together).toContainText('Quinn Farfield')
  await expect(together).toContainText('New stop')
  const atElm = proposals.filter({ hasText: 'Kai Elmwood' })
  await expect(atElm).toContainText('Elm St & Maple Dr')
  await expect(atElm).toContainText('Existing stop')
  const byHarper = proposals.filter({ hasText: 'Harper Newhome' })
  expect(await axeViolations(page)).toEqual([])

  // Moved a little on the map: a click away from the middle.
  const label = (await together.locator('strong').first().innerText()).trim()
  const before = (
    (await ok(admin.get(`stop-proposals?school_id=${willow.id}`))) as {
      label: string
      location_lat: number
      location_lon: number
    }[]
  ).find((p) => p.label === label)!
  await together.getByRole('button', { name: 'Move on map' }).click()
  await expect(page.getByText(`Click the map to move ${label}.`)).toBeVisible()
  const map = page.getByRole('region', { name: 'Stop proposals map' })
  const box = (await map.boundingBox())!
  await map.click({ position: { x: box.width / 2 + 60, y: box.height / 2 - 40 } })
  await expect(page.getByText(`Click the map to move ${label}.`)).toBeHidden()
  await expect
    .poll(async () => {
      const now = (
        (await ok(admin.get(`stop-proposals?school_id=${willow.id}`))) as (typeof before)[]
      ).find((p) => p.label === label)!
      return now.location_lat !== before.location_lat || now.location_lon !== before.location_lon
    })
    .toBe(true)

  // Decided: the new stop and the existing one approved, Harper's turned down.
  await together.getByRole('button', { name: 'Approve' }).click()
  await expect(proposals.filter({ hasText: 'Rowan Farfield' })).toHaveCount(0)
  await atElm.getByRole('button', { name: 'Approve' }).click()
  await expect(proposals.filter({ hasText: 'Kai Elmwood' })).toHaveCount(0)
  await byHarper.getByRole('button', { name: 'Reject' }).click()
  await expect(proposals).toHaveCount(0)
  await page.getByText('Decided (3)').click()
  await expect(page.getByText(`${label}: approved (2 student(s))`)).toBeVisible()
  expect(watcher.problems()).toEqual([])

  // The stop exists, and the children have their stops.
  const after = (await ok(admin.get('stops'))) as { id: number; label: string }[]
  const created = after.find((s) => s.label === label)!
  expect(created).toBeDefined()
  const students = (await ok(admin.get('students'))) as { id: number; stop_id: number | null }[]
  const stopOf = (id: number) => students.find((s) => s.id === id)!.stop_id
  expect([stopOf(rowan.id), stopOf(quinn.id)]).toEqual([created.id, created.id])
  expect(stopOf(kai.id)).toBe(elm.id)
  expect(stopOf(harper.id)).toBeNull()
  await admin.dispose()
  await page.context().close()
})
