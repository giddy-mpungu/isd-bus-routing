import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  DefectReport,
  MaintenanceDue,
  MaintenanceKind,
  MaintenanceWindow,
  Vehicle,
  VehicleMaintenance,
} from '../api/types'
import { Badge } from '../components/Badge'

/**
 * Fleet maintenance (services/api/src/isd_api/maintenance.py): service and
 * inspections falling due, drivers' defect reports, maintenance windows
 * (a bus in one isn't scheduled), and each bus's dates and service log.
 * Transportation admins and dispatchers both use it.
 */

const KINDS: { value: MaintenanceKind; label: string }[] = [
  { value: 'planned', label: 'Planned service' },
  { value: 'repair', label: 'Repair' },
  { value: 'inspection', label: 'Inspection' },
]

// "2026-10-20T06:00:00" -> "2026-10-20 06:00"
function when(stamp: string | null): string {
  return stamp ? stamp.slice(0, 16).replace('T', ' ') : 'until marked back in service'
}

export function MaintenanceSection({ vehicles }: { vehicles: Vehicle[] }) {
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [due, setDue] = useState<MaintenanceDue[]>([])
  const [defects, setDefects] = useState<DefectReport[]>([])
  const [windows, setWindows] = useState<MaintenanceWindow[]>([])

  // Taking a bus out from a defect report, or marking it fixed.
  const [actingOn, setActingOn] = useState<{ id: number; action: 'out' | 'fixed' } | null>(null)
  const [until, setUntil] = useState('')
  const [note, setNote] = useState('')

  // New maintenance window.
  const inService = vehicles.filter((v) => v.is_active)
  const [windowBus, setWindowBus] = useState('')
  const [windowKind, setWindowKind] = useState<MaintenanceKind>('planned')
  const [windowFrom, setWindowFrom] = useState('')
  const [windowUntil, setWindowUntil] = useState('')
  const [windowReason, setWindowReason] = useState('')

  // One bus's dates and service log.
  const [pickedBus, setPickedBus] = useState('')
  const busId = pickedBus || (inService.length > 0 ? String(inService[0].id) : '')
  const [loadedRecord, setRecord] = useState<VehicleMaintenance | null>(null)
  const record = loadedRecord?.vehicle_id === Number(busId) ? loadedRecord : null
  const [serviceDue, setServiceDue] = useState('')
  const [inspectionExpires, setInspectionExpires] = useState('')
  const [workOn, setWorkOn] = useState('')
  const [work, setWork] = useState('')
  const [workBy, setWorkBy] = useState('')
  const [nextDue, setNextDue] = useState('')

  const loadLists = useCallback(async () => {
    const [d, r, w] = await Promise.all([
      api.getMaintenanceDue(),
      api.getDefectReports('active'),
      api.getMaintenanceWindows(),
    ])
    setDue(d)
    setDefects(r)
    setWindows(w)
  }, [])

  function showRecord(read: VehicleMaintenance) {
    setRecord(read)
    setServiceDue(read.service_due_on ?? '')
    setInspectionExpires(read.inspection_expires_on ?? '')
  }

  useEffect(() => {
    let current = true
    Promise.all([
      api.getMaintenanceDue(),
      api.getDefectReports('active'),
      api.getMaintenanceWindows(),
    ]).then(
      ([d, r, w]) => {
        if (!current) return
        setDue(d)
        setDefects(r)
        setWindows(w)
      },
      (err: unknown) => {
        if (current) setError(err instanceof ApiError ? err.message : 'Failed to load maintenance.')
      },
    )
    return () => {
      current = false
    }
  }, [])

  useEffect(() => {
    if (!busId) return
    let current = true
    api.getVehicleMaintenance(Number(busId)).then(
      (read) => {
        if (!current) return
        setRecord(read)
        setServiceDue(read.service_due_on ?? '')
        setInspectionExpires(read.inspection_expires_on ?? '')
      },
      (err: unknown) => {
        if (current) setError(err instanceof ApiError ? err.message : 'Failed to load the bus.')
      },
    )
    return () => {
      current = false
    }
  }, [busId])

  async function save(action: () => Promise<unknown>, done: string) {
    setError(null)
    setMessage(null)
    setIsSaving(true)
    try {
      await action()
      setMessage(done)
      await loadLists()
      if (busId) showRecord(await api.getVehicleMaintenance(Number(busId)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save.')
    } finally {
      setIsSaving(false)
    }
  }

  function handleDefectAction(event: FormEvent, report: DefectReport) {
    event.preventDefault()
    if (actingOn?.action === 'out') {
      void save(
        () => api.takeOutOfServiceForDefect(report.id, until || null),
        `${report.vehicle_label} is out of service from now. Any of its runs from now on show "Needs a bus" on the Schedule page.`,
      )
    } else {
      void save(() => api.markDefectFixed(report.id, note), 'Marked fixed.')
    }
    setActingOn(null)
    setUntil('')
    setNote('')
  }

  function handleWindow(event: FormEvent) {
    event.preventDefault()
    void save(async () => {
      await api.createMaintenanceWindow({
        vehicle_id: Number(windowBus),
        kind: windowKind,
        starts_at: windowFrom,
        ends_at: windowUntil || null,
        reason: windowReason,
      })
      setWindowFrom('')
      setWindowUntil('')
      setWindowReason('')
    }, 'Maintenance window added. Runs it overlaps show "Needs a bus" on the Schedule page.')
  }

  function handleDates(event: FormEvent) {
    event.preventDefault()
    void save(
      () =>
        api.setVehicleMaintenanceDates(Number(busId), {
          service_due_on: serviceDue || null,
          inspection_expires_on: inspectionExpires || null,
        }),
      'Dates saved.',
    )
  }

  function handleRecord(event: FormEvent) {
    event.preventDefault()
    void save(async () => {
      await api.addServiceRecord(Number(busId), {
        performed_on: workOn,
        work,
        performed_by: workBy,
        next_service_due_on: nextDue || null,
      })
      setWorkOn('')
      setWork('')
      setWorkBy('')
      setNextDue('')
    }, 'Service recorded.')
  }

  return (
    <section className="maintenance-section">
      <h2>Fleet maintenance</h2>
      <p>
        A bus in a maintenance window isn&apos;t scheduled, and neither is one whose inspection has
        expired. Runs it already had show &quot;Needs a bus&quot; on the Schedule page, with spare
        buses to swap in.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="status">
          {message}
        </p>
      )}

      <h3>Due soon</h3>
      {due.length === 0 ? (
        <p>No service or inspection due in the next two weeks.</p>
      ) : (
        <ul>
          {due.map((d) => (
            <li key={`${d.vehicle_id}-${d.message}`}>
              <Badge tone={d.severity === 'critical' ? 'danger' : 'warning'}>
                {d.severity === 'critical' ? 'Off the schedule' : 'Due'}
              </Badge>{' '}
              {d.message}
            </li>
          ))}
        </ul>
      )}

      <h3>Defect reports</h3>
      {defects.length === 0 ? (
        <p>No defect reports waiting.</p>
      ) : (
        <ul className="defect-list">
          {defects.map((r) => (
            <li key={r.id}>
              <Badge tone={r.status === 'open' ? 'warning' : 'danger'}>
                {r.status === 'open' ? 'Open' : 'Bus out of service'}
              </Badge>{' '}
              {r.vehicle_label ?? 'No bus recorded'}, {r.service_date}, from {r.driver_name}:{' '}
              {r.description}
              <div>
                {r.status === 'open' && r.vehicle_label && (
                  <button
                    type="button"
                    disabled={isSaving}
                    onClick={() => setActingOn({ id: r.id, action: 'out' })}
                  >
                    Take {r.vehicle_label} out of service (report {r.id})
                  </button>
                )}{' '}
                <button
                  type="button"
                  disabled={isSaving}
                  onClick={() => setActingOn({ id: r.id, action: 'fixed' })}
                >
                  Mark report {r.id} fixed
                </button>
              </div>
              {actingOn?.id === r.id && (
                <form onSubmit={(event) => handleDefectAction(event, r)}>
                  {actingOn.action === 'out' ? (
                    <>
                      <label htmlFor={`defect-until-${r.id}`}>
                        Expected back (leave empty: until marked fixed)
                      </label>
                      <input
                        id={`defect-until-${r.id}`}
                        type="datetime-local"
                        value={until}
                        onChange={(event) => setUntil(event.target.value)}
                      />
                    </>
                  ) : (
                    <>
                      <label htmlFor={`defect-note-${r.id}`}>What was done (optional)</label>
                      <input
                        id={`defect-note-${r.id}`}
                        maxLength={500}
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                      />
                    </>
                  )}
                  <button type="submit" disabled={isSaving}>
                    {actingOn.action === 'out' ? 'Take it out now' : 'Mark fixed'}
                  </button>{' '}
                  <button type="button" onClick={() => setActingOn(null)}>
                    Cancel
                  </button>
                </form>
              )}
            </li>
          ))}
        </ul>
      )}

      <h3>Out of service now and coming up</h3>
      {windows.length === 0 ? (
        <p>Every bus is in service.</p>
      ) : (
        <table>
          <caption>Maintenance windows</caption>
          <thead>
            <tr>
              <th scope="col">Bus</th>
              <th scope="col">What</th>
              <th scope="col">From</th>
              <th scope="col">Until</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {windows.map((w) => (
              <tr key={w.id}>
                <td>
                  {w.vehicle_label} {w.current && <Badge tone="danger">Out now</Badge>}
                </td>
                <td>{w.reason}</td>
                <td>{when(w.starts_at)}</td>
                <td>{when(w.ends_at)}</td>
                <td>
                  <button
                    type="button"
                    disabled={isSaving}
                    onClick={() =>
                      void save(
                        () => api.endMaintenanceWindow(w.id),
                        w.current ? `${w.vehicle_label} is back in service.` : 'Window cancelled.',
                      )
                    }
                  >
                    {w.current
                      ? `${w.vehicle_label} back in service`
                      : `Cancel ${w.vehicle_label}'s window`}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form onSubmit={handleWindow}>
        <h4>Take a bus out of service</h4>
        <label htmlFor="window-bus">Bus</label>
        <select
          id="window-bus"
          value={windowBus}
          onChange={(event) => setWindowBus(event.target.value)}
          required
        >
          <option value="" disabled>
            Select a bus
          </option>
          {inService.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label}
            </option>
          ))}
        </select>
        <label htmlFor="window-kind">Kind</label>
        <select
          id="window-kind"
          value={windowKind}
          onChange={(event) => setWindowKind(event.target.value as MaintenanceKind)}
        >
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        <label htmlFor="window-from">From</label>
        <input
          id="window-from"
          type="datetime-local"
          value={windowFrom}
          onChange={(event) => setWindowFrom(event.target.value)}
          required
        />
        <label htmlFor="window-until">Until (leave empty: until marked back in service)</label>
        <input
          id="window-until"
          type="datetime-local"
          value={windowUntil}
          onChange={(event) => setWindowUntil(event.target.value)}
        />
        <label htmlFor="window-reason">Reason</label>
        <input
          id="window-reason"
          maxLength={255}
          value={windowReason}
          onChange={(event) => setWindowReason(event.target.value)}
          required
        />
        <button type="submit" disabled={isSaving}>
          Add maintenance window
        </button>
      </form>

      <h3>A bus&apos;s service record</h3>
      <label htmlFor="record-bus">Show the record of</label>
      <select id="record-bus" value={busId} onChange={(event) => setPickedBus(event.target.value)}>
        {inService.map((v) => (
          <option key={v.id} value={v.id}>
            {v.label}
          </option>
        ))}
      </select>
      {record && (
        <>
          <form onSubmit={handleDates}>
            <label htmlFor="record-service-due">Next service due</label>
            <input
              id="record-service-due"
              type="date"
              value={serviceDue}
              onChange={(event) => setServiceDue(event.target.value)}
            />
            <label htmlFor="record-inspection">Inspection valid until</label>
            <input
              id="record-inspection"
              type="date"
              value={inspectionExpires}
              onChange={(event) => setInspectionExpires(event.target.value)}
            />
            <button type="submit" disabled={isSaving}>
              Save {record.vehicle_label}&apos;s dates
            </button>
          </form>
          <h4>Service log</h4>
          {record.service_log.length === 0 ? (
            <p>Nothing logged for {record.vehicle_label} yet.</p>
          ) : (
            <ul>
              {record.service_log.map((s) => (
                <li key={s.id}>
                  {s.performed_on}: {s.work} ({s.performed_by})
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={handleRecord}>
            <h4>Log service</h4>
            <label htmlFor="record-on">Done on</label>
            <input
              id="record-on"
              type="date"
              value={workOn}
              onChange={(event) => setWorkOn(event.target.value)}
              required
            />
            <label htmlFor="record-work">Work done</label>
            <input
              id="record-work"
              maxLength={1000}
              value={work}
              onChange={(event) => setWork(event.target.value)}
              required
            />
            <label htmlFor="record-by">Done by</label>
            <input
              id="record-by"
              maxLength={255}
              value={workBy}
              onChange={(event) => setWorkBy(event.target.value)}
              required
            />
            <label htmlFor="record-next-due">Next service due (optional)</label>
            <input
              id="record-next-due"
              type="date"
              value={nextDue}
              onChange={(event) => setNextDue(event.target.value)}
            />
            <button type="submit" disabled={isSaving}>
              Log service for {record.vehicle_label}
            </button>
          </form>
        </>
      )}
    </section>
  )
}
