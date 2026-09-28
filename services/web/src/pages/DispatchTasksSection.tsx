import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { DispatchTask, DispatchTaskKind, Driver, Vehicle } from '../api/types'
import { STATUS_LABELS, STATUS_TONES } from '../assignmentStatus'
import { Badge } from '../components/Badge'
import { TASK_KIND_LABELS, TASK_KINDS } from '../dispatchTasks'

function formatMinuteOfDay(minute: number): string {
  return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
}

// "09:30" -> 570
function minuteOfDay(time: string): number {
  const [hours, minutes] = time.split(':').map(Number)
  return hours * 60 + minutes
}

/**
 * Spec sections 11 and 14: dispatch sends unplanned work (assist a disabled
 * bus, move a vehicle, respond to an emergency) straight to a driver's
 * tablet. The server refuses a driver or bus that can't take it; a regular
 * run it pulls them off is allowed but comes back as needing cover.
 */
export function DispatchTasksSection({
  serviceDate,
  drivers,
  vehicles,
  onChanged,
}: {
  serviceDate: string
  drivers: Driver[]
  vehicles: Vehicle[]
  // The schedule reloads so runs the task pulls a crew off show "Needs cover".
  onChanged: () => void
}) {
  const [tasks, setTasks] = useState<DispatchTask[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [kind, setKind] = useState<DispatchTaskKind>('assist_disabled_bus')
  const [driverId, setDriverId] = useState('')
  const [vehicleId, setVehicleId] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [location, setLocation] = useState('')
  const [instructions, setInstructions] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [sent, setSent] = useState<DispatchTask | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [cancellingId, setCancellingId] = useState<number | null>(null)

  const load = useCallback(async (date: string) => {
    try {
      setTasks(await api.getDispatchTasks(date))
      setLoadError(null)
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : 'Failed to load dispatch tasks.')
    }
  }, [])

  useEffect(() => {
    // Ignore a slow response for a date the dispatcher has already left.
    let current = true
    api.getDispatchTasks(serviceDate).then(
      (data) => {
        if (current) {
          setTasks(data)
          setLoadError(null)
        }
      },
      (err: unknown) => {
        if (current) {
          setLoadError(err instanceof ApiError ? err.message : 'Failed to load dispatch tasks.')
        }
      },
    )
    return () => {
      current = false
    }
  }, [serviceDate])

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    setSent(null)
    setIsSaving(true)
    try {
      const task = await api.createDispatchTask({
        kind,
        service_date: serviceDate,
        start_minute: minuteOfDay(startTime),
        end_minute: minuteOfDay(endTime),
        driver_id: Number(driverId),
        vehicle_id: vehicleId === '' ? null : Number(vehicleId),
        location: location.trim() === '' ? null : location.trim(),
        instructions,
      })
      setSent(task)
      setInstructions('')
      setLocation('')
      await load(serviceDate)
      onChanged()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Failed to send the task.')
    } finally {
      setIsSaving(false)
    }
  }

  async function handleCancel(task: DispatchTask) {
    if (!window.confirm(`Cancel task #${task.id} for ${task.driver_full_name}?`)) {
      return
    }
    setLoadError(null)
    setCancellingId(task.id)
    try {
      await api.cancelDispatchTask(task.id)
      await load(serviceDate)
      onChanged()
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : 'Failed to cancel the task.')
    } finally {
      setCancellingId(null)
    }
  }

  return (
    <section className="dispatch-tasks-section">
      <h2>Dispatch tasks for {serviceDate}</h2>
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {tasks.length === 0 ? (
        <p className="status">No dispatch tasks for this date.</p>
      ) : (
        <ul>
          {tasks.map((task) => (
            <li key={task.id}>
              {formatMinuteOfDay(task.start_minute)}–{formatMinuteOfDay(task.end_minute)}{' '}
              <strong>{TASK_KIND_LABELS[task.kind]}</strong> — {task.driver_full_name}
              {task.vehicle_label && `, ${task.vehicle_label}`}
              {task.location && ` at ${task.location}`}{' '}
              {task.cancelled ? (
                <Badge tone="neutral">Cancelled</Badge>
              ) : (
                <Badge tone={STATUS_TONES[task.status]}>{STATUS_LABELS[task.status]}</Badge>
              )}
              <div>{task.instructions}</div>
              {task.routes_needing_cover.length > 0 && (
                <p className="dispatch-task-cover">
                  Needs cover: {task.routes_needing_cover.join('; ')}
                </p>
              )}
              {!task.cancelled && task.status !== 'completed' && (
                <button
                  type="button"
                  className="btn-danger"
                  disabled={cancellingId === task.id}
                  onClick={() => void handleCancel(task)}
                >
                  Cancel task
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <h3>Send a task to a driver</h3>
      <form onSubmit={(event) => void handleCreate(event)}>
        <label htmlFor="task-kind">Task</label>
        <select
          id="task-kind"
          value={kind}
          onChange={(event) => setKind(event.target.value as DispatchTaskKind)}
        >
          {TASK_KINDS.map((k) => (
            <option key={k} value={k}>
              {TASK_KIND_LABELS[k]}
            </option>
          ))}
        </select>
        <label htmlFor="task-driver">Assign to driver</label>
        <select
          id="task-driver"
          value={driverId}
          onChange={(event) => setDriverId(event.target.value)}
          required
        >
          <option value="" disabled>
            Select a driver
          </option>
          {drivers
            .filter((d) => d.is_active)
            .map((d) => (
              <option key={d.id} value={d.id}>
                {d.full_name}
              </option>
            ))}
        </select>
        <label htmlFor="task-vehicle">Vehicle (optional)</label>
        <select
          id="task-vehicle"
          value={vehicleId}
          onChange={(event) => setVehicleId(event.target.value)}
        >
          <option value="">No vehicle</option>
          {vehicles
            .filter((v) => v.is_active)
            .map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
        </select>
        <label htmlFor="task-start">Start time</label>
        <input
          id="task-start"
          type="time"
          value={startTime}
          onChange={(event) => setStartTime(event.target.value)}
          required
        />
        <label htmlFor="task-end">End time</label>
        <input
          id="task-end"
          type="time"
          value={endTime}
          onChange={(event) => setEndTime(event.target.value)}
          required
        />
        <label htmlFor="task-location">Where (optional)</label>
        <input
          id="task-location"
          value={location}
          maxLength={255}
          onChange={(event) => setLocation(event.target.value)}
        />
        <label htmlFor="task-instructions">Instructions for the driver</label>
        <textarea
          id="task-instructions"
          value={instructions}
          maxLength={1000}
          onChange={(event) => setInstructions(event.target.value)}
          required
        />
        {formError && (
          <p role="alert" className="error">
            {formError}
          </p>
        )}
        {sent && (
          <p className="status">
            Task #{sent.id} sent to {sent.driver_full_name}.
            {sent.routes_needing_cover.length > 0 &&
              ` These runs now need cover: ${sent.routes_needing_cover.join('; ')}.`}
          </p>
        )}
        <button type="submit" disabled={isSaving}>
          {isSaving ? 'Sending…' : 'Send to driver'}
        </button>
      </form>
    </section>
  )
}
