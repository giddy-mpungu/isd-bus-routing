import type { Page } from '@playwright/test'

/**
 * Collects what should never happen while a page is used: errors in the
 * browser console, uncaught exceptions, and server errors (5xx) from the
 * API. Call `problems()` at the end of a test and expect it to be empty.
 */
export function watch(page: Page): { problems: () => string[] } {
  const found: string[] = []
  page.on('console', (message) => {
    // The browser logs every 4xx as an error; some are expected (a
    // student's page asking for a parent-only setting), and the app shows
    // the ones that matter. Server errors are caught below instead.
    const expected4xx = /Failed to load resource: the server responded with a status of 4\d\d/
    if (message.type() === 'error' && !expected4xx.test(message.text())) {
      found.push(`console: ${message.text()}`)
    }
  })
  page.on('pageerror', (error) => found.push(`page error: ${error.message}`))
  page.on('response', (response) => {
    if (response.status() >= 500) {
      found.push(`${response.status()} from ${response.request().method()} ${response.url()}`)
    }
  })
  return { problems: () => [...found] }
}
