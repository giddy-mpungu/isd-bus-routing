import { createRequire } from 'node:module'
import type { Page } from '@playwright/test'

const require = createRequire(import.meta.url)

/**
 * WCAG 2.1 A and AA problems on the page as it is now, contrast included
 * (a real browser lays the page out, unlike the unit tests' jsdom), as
 * readable lines; empty when there are none.
 */
export async function axeViolations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') })
  return page.evaluate(async () => {
    const results = await (
      window as unknown as {
        axe: {
          run: (
            context: Document,
            options: object,
          ) => Promise<{
            violations: { id: string; help: string; nodes: { target: string[] }[] }[]
          }>
        }
      }
    ).axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
    })
    return results.violations.flatMap((v) =>
      v.nodes.map((n) => `${v.id}: ${v.help} (${n.target.join(' ')})`),
    )
  })
}
