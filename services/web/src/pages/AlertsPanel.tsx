import { useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { AlertSeverity, DayAlerts } from '../api/types'
import { Badge } from '../components/Badge'

const REFRESH_MS = 60_000

const SEVERITY_LABELS: Record<AlertSeverity, string> = {
  critical: 'Critical',
  warning: 'Warning',
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
}: {
  serviceDate: string
  refreshToken: number
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
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
