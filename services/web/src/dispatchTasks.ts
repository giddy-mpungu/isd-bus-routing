import type { DispatchTaskKind } from './api/types'
import type { Phrase } from './i18n'

// Spec section 14's unplanned assignments, in the order dispatch picks them.
export const TASK_KINDS: DispatchTaskKind[] = [
  'cover_route',
  'assist_disabled_bus',
  'transfer_passengers',
  'return_to_school',
  'move_vehicle',
  'assist_driver',
  'emergency',
  'other',
]

// Phrases (src/i18n): the driver app shows them translated.
export const TASK_KIND_LABELS: Record<DispatchTaskKind, Phrase> = {
  cover_route: 'Cover another route',
  assist_disabled_bus: 'Assist a disabled bus',
  transfer_passengers: 'Pick up transferred passengers',
  return_to_school: 'Return to a school',
  move_vehicle: 'Move a vehicle',
  assist_driver: 'Assist another driver',
  emergency: 'Respond to an emergency',
  other: 'Other instruction',
}
