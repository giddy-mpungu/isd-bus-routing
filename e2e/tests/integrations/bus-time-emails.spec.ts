import { expect, test } from '@playwright/test'
import { linkIn, needsMail, waitForMail } from '../helpers/mail'
import { api, day } from '../helpers/roles'

/**
 * The background worker emails a family when their child's bus time moves
 * 10 minutes or more from the plan, and the email's "stop these emails"
 * link works. Needs the harness's --worker and a captured inbox.
 *
 * The demo district's routes have no stops or planned times, so this sets
 * one up through the API: a Maple Valley afternoon route through Mia's stop
 * whose planned time is well off the estimate, starting 45 minutes from now
 * in a district time zone where it's around noon (the worker only emails on
 * the service day, after 05:30, before the time has passed).
 */
needsMail()

test("Mia's bus time changes: Pat is emailed, and the email's link turns them off", async ({
  page,
  baseURL,
}) => {
  test.skip(!process.env.E2E_WORKER, 'Needs the background worker (harness --worker)')
  const admin = await api('transportation_admin')
  const ok = async (response: Promise<import('@playwright/test').APIResponse>) => {
    const r = await response
    expect(r.ok(), `${r.url()}: ${await r.text()}`).toBe(true)
    return r.json()
  }

  // A district clock at about noon today (UTC date), so "today" and
  // "not yet passed" hold whatever time the test runs.
  const now = new Date()
  const offset = 12 - now.getUTCHours()
  const zone = offset === 0 ? 'Etc/GMT' : `Etc/GMT${offset > 0 ? '-' : '+'}${Math.abs(offset)}`
  await ok(
    admin.put('ridership-rules', {
      data: { timezone: zone, am_cutoff_minute: null, pm_cutoff_minute: null },
    }),
  )
  const localMinute = 12 * 60 + now.getUTCMinutes()
  const start = localMinute + 45

  const schools = (await ok(admin.get('schools'))) as { id: number; name: string }[]
  const maple = schools.find((s) => s.name === 'Maple Valley High School')!
  const stops = (await ok(admin.get('stops'))) as { id: number; label: string }[]
  const oak = stops.find((s) => s.label === 'Oak St & 3rd Ave')!

  const route = (await ok(
    admin.post('route-templates', {
      data: {
        school_id: maple.id,
        direction: 'pm',
        window_earliest: start,
        window_latest: start + 60,
        duration_minutes: 45,
        buffer_minutes: 0,
        days_of_week: [0, 1, 2, 3, 4, 5, 6],
      },
    }),
  )) as { id: number }
  // Planned 35 minutes after the bus leaves school; the estimate is a few.
  await ok(
    admin.put(`route-templates/${route.id}/stops`, {
      data: { stops: [{ stop_id: oak.id, minutes_from_start: 35 }] },
    }),
  )
  await ok(admin.post(`schedule/${day()}/generate-from-templates`))
  await ok(admin.post('schedule', { data: { service_date: day() } }))
  await admin.dispose()

  // The worker notices within a pass or two.
  const email = await waitForMail(
    'parent.alvarez@demo.example.org',
    /Bus time change for Mia Alvarez/,
  )
  expect(email.text).toContain('Oak St & 3rd Ave')
  expect(email.text).toMatch(/\(planned \d\d:\d\d\)/)

  // The link in the email asks before it changes anything...
  await page.goto(linkIn(email.text, `${baseURL}/email-preferences`))
  await expect(page.getByRole('heading', { name: 'Bus time emails' })).toBeVisible()
  await page.getByRole('button', { name: 'Stop bus time emails' }).click()
  await expect(page.getByText("Done: you won't get bus time emails any more.")).toBeVisible()

  // ...and then they're off.
  const parent = await api('parent')
  const settings = (await (await parent.get('users/me/notification-settings')).json()) as {
    eta_emails: boolean
  }
  expect(settings.eta_emails).toBe(false)
  await parent.dispose()
})
