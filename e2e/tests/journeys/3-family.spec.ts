import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { axeViolations } from '../helpers/axe'
import { statePath } from '../helpers/env'
import { as } from '../helpers/roles'
import { watch } from '../helpers/watch'

/**
 * A parent's day (Pat Alvarez, guardian of Mia and Emma): a ride changed and
 * changed back, the bus looked for, bus-time emails turned off and on, the
 * records downloaded, and a correction asked for that the transportation
 * office then accepts.
 */
test.use({ storageState: statePath('parent') })

test('a parent changes a ride, downloads records and gets a correction', async ({
  page,
  browser,
  baseURL,
}) => {
  const watcher = watch(page)
  await page.goto('/family')
  const mia = page.locator('.family-card', { hasText: 'Mia Alvarez' })
  await expect(mia).toContainText('Maple Valley High School')
  await expect(page.locator('.family-card', { hasText: 'Emma Ibrahim' })).toBeVisible()

  // Not riding this afternoon, then riding after all.
  await mia.getByRole('button', { name: 'Mark not riding PM' }).click()
  await expect(mia.getByText('PM: Not riding')).toBeVisible()
  await mia.getByRole('button', { name: 'Mark riding PM' }).click()
  await expect(mia.getByText('PM: Riding')).toBeVisible()

  // Where's the bus? (No GPS in a test run: it says so.)
  await mia.getByRole('button', { name: 'Locate bus' }).first().click()
  await expect(mia.locator('.bus-position, [role="alert"]').first()).toBeVisible()

  // Bus-time emails off, still off after a reload, then on again.
  const emails = page.getByLabel(/Email me when my child's bus time changes/)
  await expect(emails).toBeChecked()
  await emails.click() // saved first, then shown: wait for it below
  await expect(emails).not.toBeChecked()
  await page.reload()
  await expect(emails).not.toBeChecked()
  await emails.click()
  await expect(emails).toBeChecked()

  // Everything held about Mia, as a file.
  const download = page.waitForEvent('download')
  await mia.getByRole('link', { name: "Download Mia's records" }).click()
  const records = readFileSync(await (await download).path(), 'utf8')
  expect(records).toContain('Transportation records: Mia Alvarez')
  expect(records).toContain('Oak St &amp; 3rd Ave')

  // Something's wrong in the record: the family asks...
  await mia.getByRole('button', { name: "Something's wrong?" }).click()
  await mia.getByLabel("What's wrong in Mia's record?").fill('Her stop is listed as Oak St (e2e)')
  await mia.getByLabel('What should it say?').fill('Elm St & Maple Dr')
  await mia.getByRole('button', { name: 'Send to the transportation office' }).click()
  await expect(mia.getByText(/^Sent\. The transportation office/)).toBeVisible()
  await expect(mia.locator('.correction-list li', { hasText: 'Oak St (e2e)' })).toContainText(
    'Waiting for an answer',
  )
  expect(await axeViolations(page)).toEqual([])
  expect(watcher.problems()).toEqual([])

  // ...the transportation office answers in Setup, Corrections...
  const office = await as(browser, 'transportation_admin', baseURL)
  await office.goto('/setup?tab=corrections')
  const request = office.locator('.corrections-list li', { hasText: 'Oak St (e2e)' })
  await expect(request).toContainText('Mia Alvarez')
  await request.getByLabel('Answer to the family').fill('Moved Mia to the Elm St & Maple Dr stop.')
  await request.getByRole('button', { name: 'Accept (fixed)' }).click()
  await expect(office.locator('.corrections-list li', { hasText: 'Oak St (e2e)' })).toHaveCount(0)
  await office.context().close()

  // ...and the family sees the answer.
  await page.reload()
  const answered = mia.locator('.correction-list li', { hasText: 'Oak St (e2e)' })
  await expect(answered).toContainText('Corrected')
  await expect(answered).toContainText('Answer: Moved Mia to the Elm St & Maple Dr stop.')
})
