import type { AssignmentStatus } from './api/types'
import type { BadgeTone } from './components/Badge'
import type { Phrase } from './i18n'

// Phrases (src/i18n): the driver app shows them translated.
export const STATUS_LABELS: Record<AssignmentStatus, Phrase> = {
  sent: 'Sent',
  received: 'Received',
  acknowledged: 'Acknowledged',
  en_route: 'En route',
  arrived: 'Arrived',
  in_progress: 'In progress',
  completed: 'Completed',
  no_show: 'No-show',
}

export const STATUS_TONES: Record<AssignmentStatus, BadgeTone> = {
  sent: 'warning',
  received: 'neutral',
  acknowledged: 'info',
  en_route: 'info',
  arrived: 'info',
  in_progress: 'info',
  completed: 'success',
  no_show: 'danger',
}

// The driver's single next step for each state (large, one tap).
export const NEXT_STEP: Partial<Record<AssignmentStatus, { label: Phrase; to: AssignmentStatus }>> =
  {
    sent: { label: 'Acknowledge', to: 'acknowledged' },
    received: { label: 'Acknowledge', to: 'acknowledged' },
    acknowledged: { label: "I'm en route", to: 'en_route' },
    en_route: { label: 'Arrived', to: 'arrived' },
    arrived: { label: 'Start run', to: 'in_progress' },
    in_progress: { label: 'Complete run', to: 'completed' },
  }

// The bus is moving or about to: position reporting is on.
export const UNDERWAY: AssignmentStatus[] = ['en_route', 'arrived', 'in_progress']

export const FINISHED: AssignmentStatus[] = ['completed', 'no_show']
