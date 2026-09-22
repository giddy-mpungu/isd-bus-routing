import type { ReactNode } from 'react'

// Tiny presentational status pill, shared across the pages that render
// a status word (assignment/run status, active/inactive, locked, etc.)
// instead of each page re-implementing its own colored span.
export type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

export function Badge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}
