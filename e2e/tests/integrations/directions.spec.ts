import { expect, test } from '@playwright/test'
import { seededAccounts } from '../helpers/env'
import { mapRequests, needsMaps, type MapRequest } from '../helpers/maps'
import { api } from '../helpers/roles'
import { signIn } from '../helpers/signin'
import { watch } from '../helpers/watch'

/**
 * Turn-by-turn directions on the driver's tablet (spec sections 6 and 10),
 * from OpenRouteService (here the stand-in, fakes/maps.mjs, which names
 * each road after its stop): Sam's afternoon route at Willow Creek, the
 * bus's size sent so the route suits it, stop by stop; then dispatch
 * closes the road at one stop, Sam is told, and the next directions go
 * around it. Needs the harness's --maps.
 */
needsMaps()

const sam = () => seededAccounts().find((a) => a.email.startsWith('driver.sam'))!
const NOTE = 'Birch Ln closed for a water main repair (e2e)'

function avoidAreas(request: MapRequest | undefined): number {
  const avoid = request?.body?.options?.avoid_polygons
  if (!avoid) return 0
  return avoid.type === 'MultiPolygon' ? avoid.coordinates.length : 1
}

async function lastDirections(): Promise<MapRequest | undefined> {
  return (await mapRequests())
    .filter((r) => r.service === 'ors' && r.path?.endsWith('/geojson'))
    .at(-1)
}

test('Sam follows directions stop by stop, and around a closed road', async ({ page }) => {
  const admin = await api('transportation_admin')
  const ok = async (response: Promise<import('@playwright/test').APIResponse>) => {
    const r = await response
    expect(r.ok(), `${r.url()}: ${await r.text()}`).toBe(true)
    return r.json()
  }
  // A district clock at about noon today (UTC date), so "today" is the
  // same day whatever time the test runs (closures are told for today).
  const offset = 12 - new Date().getUTCHours()
  const zone = offset === 0 ? 'Etc/GMT' : `Etc/GMT${offset > 0 ? '-' : '+'}${Math.abs(offset)}`
  await ok(
    admin.put('ridership-rules', {
      data: { timezone: zone, am_cutoff_minute: null, pm_cutoff_minute: null },
    }),
  )

  // Willow Creek's afternoon route gets three stops.
  const schools = (await ok(admin.get('schools'))) as { id: number; name: string }[]
  const willow = schools.find((s) => s.name === 'Willow Creek Elementary')!
  const stops = (await ok(admin.get('stops'))) as { id: number; label: string }[]
  const stop = (label: string) => stops.find((s) => s.label === label)!.id
  const templates = (await ok(admin.get('route-templates'))) as {
    id: number
    school_id: number
    direction: string
  }[]
  const route = templates.find((t) => t.school_id === willow.id && t.direction === 'pm')!
  await ok(
    admin.put(`route-templates/${route.id}/stops`, {
      data: {
        stops: [
          { stop_id: stop('Oak St & 3rd Ave'), minutes_from_start: 10 },
          { stop_id: stop('Birch Ln Cul-de-sac'), minutes_from_start: 20 },
          { stop_id: stop('Pinecrest Apartments'), minutes_from_start: 30 },
        ],
      },
    }),
  )
  await admin.dispose()

  const watcher = watch(page)
  await signIn(page, sam().email, sam().password)
  // (The bus-time email test may have given Sam another route with stops.)
  const run = page
    .locator('.driver-run-card', { has: page.getByRole('heading', { name: 'Stops in order' }) })
    .filter({ hasText: 'Willow Creek Elementary' })
    .filter({ hasText: 'Pinecrest Apartments' })
  await run.getByRole('button', { name: 'Directions', exact: true }).click()

  // From school to the first stop, then on to the next.
  await expect(run.locator('.directions-summary')).toContainText('Whole route:')
  await expect(run.locator('.directions-leg')).toContainText('To Oak St & 3rd Ave')
  await expect(run.locator('.directions-steps')).toContainText('Drive along E2E Road 1')
  await run.getByRole('button', { name: 'Next stop' }).click()
  await expect(run.locator('.directions-leg')).toContainText('To Birch Ln Cul-de-sac')
  await expect(run.locator('.directions-steps')).toContainText('Drive along E2E Road 2')
  await expect(run.locator('.directions-attribution')).toContainText('openrouteservice')

  // What was asked: school then the three stops, for a bus this size, with
  // the district's flood-prone crossing to be avoided.
  const first = await lastDirections()
  expect(first?.body?.coordinates).toHaveLength(4)
  expect(Object.keys(first?.body?.options?.profile_params?.restrictions ?? {})).not.toHaveLength(0)
  const before = avoidAreas(first)
  expect(before).toBeGreaterThan(0)

  // Dispatch closes the road at Birch Ln.
  const dispatch = await api('dispatcher')
  await ok(
    dispatch.post('road-closures', {
      data: {
        kind: 'road_closed',
        note: NOTE,
        location_lat: 29.765,
        location_lon: -95.392,
        radius_m: 150,
      },
    }),
  )
  await dispatch.dispose()

  // Sam is told, and the directions now go around it.
  await page.reload()
  const closure = run.locator('.driver-closure')
  await expect(closure).toContainText('Road closure near your route.')
  await expect(closure).toContainText(NOTE)
  await expect(closure).toContainText('the Birch Ln Cul-de-sac stop is inside it')
  await run.getByRole('button', { name: 'Directions', exact: true }).click()
  await expect(run.locator('.directions-summary')).toContainText('Whole route:')
  await expect.poll(async () => avoidAreas(await lastDirections())).toBe(before + 1)
  expect(watcher.problems()).toEqual([])
})
