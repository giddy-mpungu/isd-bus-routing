// Spec section 19, "district tablets": a driver's day stays readable when
// the tablet loses signal. The last day loaded is kept on the tablet, for
// that driver and that date only (it names the riders, so nothing older is
// kept, and logging out removes it). Changes still need the server.
import type { DriverAssignment, DriverDispatchTask, DriverFieldTrip } from './api/types'

const PREFIX = 'isd-driver-day:'

export interface SavedDay {
  savedAt: string
  assignments: DriverAssignment[]
  tasks: DriverDispatchTask[]
  trips: DriverFieldTrip[]
}

function key(userId: number, date: string): string {
  return `${PREFIX}${userId}:${date}`
}

function savedKeys(): string[] {
  const keys: string[] = []
  for (let i = 0; i < localStorage.length; i += 1) {
    const k = localStorage.key(i)
    if (k?.startsWith(PREFIX)) keys.push(k)
  }
  return keys
}

export function saveDay(userId: number, date: string, day: Omit<SavedDay, 'savedAt'>): void {
  try {
    const mine = key(userId, date)
    for (const k of savedKeys()) if (k !== mine) localStorage.removeItem(k)
    localStorage.setItem(mine, JSON.stringify({ ...day, savedAt: new Date().toISOString() }))
  } catch {
    // Storage full or blocked: the page still works while online.
  }
}

export function savedDay(userId: number, date: string): SavedDay | null {
  try {
    const raw = localStorage.getItem(key(userId, date))
    return raw ? (JSON.parse(raw) as SavedDay) : null
  } catch {
    return null
  }
}

export function forgetSavedDays(): void {
  try {
    for (const k of savedKeys()) localStorage.removeItem(k)
  } catch {
    // Nothing to remove.
  }
}
