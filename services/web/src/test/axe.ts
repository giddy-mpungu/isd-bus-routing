import axe from 'axe-core'

/**
 * WCAG 2.1 A and AA problems axe-core finds in `container`, as readable
 * lines (empty when there are none). Colour contrast is left to the real-
 * browser check: jsdom does no layout, so it can't measure colours.
 */
export async function axeViolations(container: Element = document.body): Promise<string[]> {
  const results = await axe.run(container, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
    rules: { 'color-contrast': { enabled: false } },
  })
  return results.violations.flatMap((v) =>
    v.nodes.map((n) => `${v.id}: ${v.help} (${n.target.join(' ')})`),
  )
}
