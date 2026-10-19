import { expect, test } from '@playwright/test'
import { type Role } from '../helpers/env'
import { api, as, day } from '../helpers/roles'

/**
 * Each role reaches only what it's for (spec section 17): the staff
 * console's pages say so instead of showing anything, and the API refuses
 * the same things directly, so hiding a link is never the only guard.
 */

const STAFF_PAGES = ['/schedule', '/setup', '/field-trips', '/templates', '/reports', '/users']

for (const role of ['driver', 'parent', 'student', 'school_admin'] as Role[]) {
  test(`${role} can't open the staff console`, async ({ browser, baseURL }) => {
    const page = await as(browser, role, baseURL)
    for (const path of STAFF_PAGES) {
      await page.goto(path)
      await expect(page.getByText(/isn't authorized to use/), path).toBeVisible()
    }
    await page.context().close()
  })
}

test('a dispatcher can do dispatch, but not manage users', async ({ browser, baseURL }) => {
  const page = await as(browser, 'dispatcher', baseURL)
  await page.goto('/users')
  await expect(page.getByText(/isn't authorized to use user management/)).toBeVisible()
  await page.context().close()
})

test('signed out, nothing opens', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, ignoreHTTPSErrors: true })
  const page = await context.newPage()
  for (const path of ['/family', '/driver', '/schedule', '/account']) {
    await page.goto(path)
    await expect(page, path).toHaveURL(/\/login/)
  }
  await context.close()
})

test('the API refuses what each role is not for', async () => {
  const refusals: [Role, string][] = [
    ['parent', 'users'],
    ['parent', 'students'],
    ['parent', `schedule/${day()}/assignments`],
    ['parent', 'maintenance/windows'],
    ['student', 'students'],
    ['driver', 'students'],
    ['driver', 'users'],
    ['driver', 'audit-log'],
    ['school_admin', 'users'],
    ['school_admin', 'maintenance/defects'],
    ['dispatcher', 'users'],
    ['dispatcher', 'audit-log'],
  ]
  for (const [role, path] of refusals) {
    const as = await api(role)
    expect((await as.get(path)).status(), `${role} GET ${path}`).toBe(403)
    await as.dispose()
  }
})

test("a student sees only their own record, and a parent only their own children's", async () => {
  const parent = await api('parent')
  const family = (await (await parent.get(`students/my-family?service_date=${day()}`)).json()) as {
    student_id: number
    full_name: string
  }[]
  expect(family.map((f) => f.full_name).sort()).toEqual(['Emma Ibrahim', 'Mia Alvarez'])
  const mia = family.find((f) => f.full_name === 'Mia Alvarez')!
  expect((await parent.get(`students/${mia.student_id}/records`)).status()).toBe(200)
  await parent.dispose()

  // Noah, a student, asking for Mia's records: as if she didn't exist.
  const student = await api('student')
  const own = (await (await student.get(`students/my-family?service_date=${day()}`)).json()) as {
    full_name: string
  }[]
  expect(own.map((f) => f.full_name)).toEqual(['Noah Bennett'])
  expect((await student.get(`students/${mia.student_id}/records`)).status()).toBe(404)
  await student.dispose()
})
