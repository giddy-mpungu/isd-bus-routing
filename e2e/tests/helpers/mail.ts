import { expect, test } from '@playwright/test'
import { MAILPIT_URL } from './env'

/**
 * The captured inbox (Mailpit, standing in for the district's mail
 * server). Tests that need mail skip when the harness has none.
 */

export function needsMail() {
  test.skip(!MAILPIT_URL, 'No captured inbox in this run (E2E_MAILPIT_URL unset)')
}

interface Summary {
  ID: string
  Created: string
  Subject: string
  To: { Address: string }[]
}

// Mail from an earlier run or round (another database, other links) is
// never the one a test is waiting for; a little slack for the clocks.
const STARTED = Date.now() - 5_000

/** The newest message to `to` whose subject matches, waiting for it to arrive. */
export async function waitForMail(to: string, subject: RegExp): Promise<{ text: string }> {
  let found: Summary | undefined
  await expect
    .poll(
      async () => {
        const response = await fetch(`${MAILPIT_URL}/api/v1/messages?limit=50`)
        const body = (await response.json()) as { messages: Summary[] }
        found = body.messages.find(
          (m) =>
            Date.parse(m.Created) >= STARTED &&
            m.To.some((t) => t.Address === to) &&
            subject.test(m.Subject),
        )
        return found !== undefined
      },
      { timeout: 30_000, message: `an email to ${to} matching ${subject}` },
    )
    .toBe(true)
  const message = await fetch(`${MAILPIT_URL}/api/v1/message/${found!.ID}`)
  const body = (await message.json()) as { Text: string }
  return { text: body.Text }
}

/** The first link in an email that starts with `prefix`. */
export function linkIn(text: string, prefix: string): string {
  const match = text.match(new RegExp(`${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\S+`))
  if (!match) throw new Error(`No link starting ${prefix} in:\n${text}`)
  return match[0]
}
