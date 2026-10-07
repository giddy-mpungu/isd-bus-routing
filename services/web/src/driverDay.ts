import type { DriverAssignment, DriverDispatchTask, DriverFieldTrip, TripStatus } from './api/types'
import { FINISHED, UNDERWAY } from './assignmentStatus'
import type { Phrase } from './i18n'

// Spec sections 11 and 14: a driver's day is one sequence of jobs (regular
// runs, field trips, dispatch tasks), shown as Current, Next and Later.
export type DayItem =
  | { type: 'run'; key: string; start: number; end: number; run: DriverAssignment }
  | { type: 'task'; key: string; start: number; end: number; task: DriverDispatchTask }
  | { type: 'trip'; key: string; start: number; end: number; trip: DriverFieldTrip }

export type QueueSlot = 'current' | 'next' | 'later' | 'done' | 'cancelled'

export const SLOT_LABELS: Record<QueueSlot, Phrase> = {
  current: 'Current',
  next: 'Next',
  later: 'Later',
  done: 'Done',
  cancelled: 'Cancelled',
}

const TRIP_UNDERWAY: TripStatus[] = ['dispatched', 'in_progress', 'returning']

function isCancelled(item: DayItem): boolean {
  return item.type === 'task' && item.task.cancelled
}

function isFinished(item: DayItem): boolean {
  if (item.type === 'trip') return item.trip.status === 'completed'
  return FINISHED.includes(item.type === 'run' ? item.run.status : item.task.status)
}

export function isUnderway(item: DayItem): boolean {
  if (isCancelled(item)) return false
  if (item.type === 'trip') return TRIP_UNDERWAY.includes(item.trip.status)
  return UNDERWAY.includes(item.type === 'run' ? item.run.status : item.task.status)
}

/** The day in time order, each job with its place in the queue. Work
 * already under way is current even if an earlier job was never closed. */
export function buildDay(
  runs: DriverAssignment[],
  tasks: DriverDispatchTask[],
  trips: DriverFieldTrip[],
): { item: DayItem; slot: QueueSlot }[] {
  const items: DayItem[] = [
    ...runs.map((run) => ({
      type: 'run' as const,
      key: `run-${run.id}`,
      start: run.start_minute,
      end: run.end_minute,
      run,
    })),
    ...tasks.map((task) => ({
      type: 'task' as const,
      key: `task-${task.id}`,
      start: task.start_minute,
      end: task.end_minute,
      task,
    })),
    ...trips.map((trip) => ({
      type: 'trip' as const,
      key: `trip-${trip.id}`,
      start: trip.start_minute,
      end: trip.end_minute,
      trip,
    })),
  ].sort((a, b) => a.start - b.start || a.end - b.end)

  const pending = items
    .filter((item) => !isCancelled(item) && !isFinished(item))
    .sort((a, b) => Number(isUnderway(b)) - Number(isUnderway(a)) || a.start - b.start)
  const slots = new Map<string, QueueSlot>()
  pending.forEach((item, index) =>
    slots.set(item.key, index === 0 ? 'current' : index === 1 ? 'next' : 'later'),
  )
  return items.map((item) => ({
    item,
    slot: isCancelled(item) ? 'cancelled' : (slots.get(item.key) ?? 'done'),
  }))
}
