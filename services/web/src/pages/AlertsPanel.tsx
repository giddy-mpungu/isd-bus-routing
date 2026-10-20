import { useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { AlertSeverity, DayAlerts, Spares } from '../api/types'
import { Badge } from '../components/Badge'

const REFRESH_MS = 60_000

const SEVERITY_LABELS: Record<AlertSeverity, string> = {
  critical: 'Critical',
  warning: 'Warning',
}

/**
 * For a run that lost its bus: the spare buses that could take over the
 * crew's day (services/api/src/isd_api/maintenance.py), and a swap.
 */
function SpareBusPicker({
  assignmentId,
  onSwapped,
}: {
  assignmentId: number
  onSwapped: () => void
}) {
  const [spares, setSpares] = useState<Spares | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  async function find() {
    setError(null)
    setIsBusy(true)
    try {
      setSpares(await api.getSpareVehicles(assignmentId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to find spare buses.')
    } finally {
      setIsBusy(false)
    }
  }

  async function swap(crewId: number, vehicleId: number) {
    setError(null)
    setIsBusy(true)
    try {
      await api.swapCrewVehicle(crewId, vehicleId)
      setSpares(null)
      onSwapped()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to swap the bus.')
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <div className="spare-bus-picker">
      {spares === null ? (
        <button type="button" disabled={isBusy} onClick={() => void find()}>
          Find a spare bus
        </button>
      ) : spares.spares.length === 0 ? (
        <p className="status">
          No spare bus fits this crew&apos;s day. Run the schedule again, or pair the driver with
          another bus.
        </p>
      ) : (
        <ul>
          {spares.spares.map((s) => (
            <li key={s.vehicle_id}>
              <button
                type="button"
                disabled={isBusy}
                onClick={() => void swap(spares.crew_id, s.vehicle_id)}
              >
                Swap {s.label} in for {spares.current_vehicle_label}
              </button>{' '}
              {s.allowable_capacity != null
                ? `${s.allowable_capacity} seats${s.spare_seats != null ? `, ${s.spare_seats} to spare` : ''}`
                : 'capacity not recorded'}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Spec sections 9, 13.1 and 14: what needs dispatch's attention today,
 * most urgent first. The server works it out from live data, so an alert
 * goes away once its cause is dealt with. Refreshes every minute and
 * whenever the schedule reloads (`refreshToken` changes).
 */
export function AlertsPanel({
  serviceDate,
  refreshToken,
  onScheduleChanged,
}: {
  serviceDate: string
  refreshToken: number
  // After a change made from an alert (a spare bus swapped in).
  onScheduleChanged?: () => void
}) {
  const [data, setData] = useState<DayAlerts | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    const load = () =>
      api.getAlerts(serviceDate).then(
        (result) => {
          if (current) {
            setData(result)
            setError(null)
          }
        },
        (err: unknown) => {
          if (current) {
            setError(err instanceof ApiError ? err.message : 'Failed to load alerts.')
          }
        },
      )
    void load()
    const intervalId = window.setInterval(() => void load(), REFRESH_MS)
    return () => {
      current = false
      window.clearInterval(intervalId)
    }
  }, [serviceDate, refreshToken])

  const alerts = data?.service_date === serviceDate ? data.alerts : []
  const critical = alerts.filter((a) => a.severity === 'critical').length

  return (
    <section className="alerts-panel" aria-labelledby="alerts-heading">
      <h2 id="alerts-heading">
        Needs attention {critical > 0 && <Badge tone="danger">{critical} critical</Badge>}{' '}
        {alerts.length > critical && (
          <Badge tone="warning">{alerts.length - critical} warning</Badge>
        )}
      </h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {data?.district_time && data.service_date === serviceDate && (
        <p className="status">As of {data.district_time} district time.</p>
      )}
      {data && alerts.length === 0 && !error && <p className="status">Nothing needs attention.</p>}
      {alerts.length > 0 && (
        <ul className="alerts-list">
          {alerts.map((alert) => (
            <li
              key={`${alert.kind}-${alert.entity_type}-${alert.entity_id}`}
              className={`alert-item alert-${alert.severity}`}
            >
              <Badge tone={alert.severity === 'critical' ? 'danger' : 'warning'}>
                {SEVERITY_LABELS[alert.severity]}
              </Badge>{' '}
              {alert.message}
              {(alert.kind === 'needs_bus' || alert.kind === 'over_capacity') &&
                alert.entity_type === 'assignment' && (
                  <SpareBusPicker
                    assignmentId={alert.entity_id}
                    onSwapped={() => onScheduleChanged?.()}
                  />
                )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
