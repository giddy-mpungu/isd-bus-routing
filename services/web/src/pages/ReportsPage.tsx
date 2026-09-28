import { useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Report, ReportCell, ReportName } from '../api/types'

const REPORTS: { name: ReportName; label: string; note?: string }[] = [
  { name: 'assignments', label: 'Assignments and on-time performance' },
  { name: 'field-trips', label: 'Field trips' },
  { name: 'absences', label: 'Driver absences and cover' },
  { name: 'driver-reports', label: 'Incident and vehicle defect reports' },
  { name: 'dispatch-tasks', label: 'Dispatch tasks' },
  { name: 'positions', label: 'GPS position history', note: 'Up to 7 days at a time.' },
]

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return isoDate(d)
}

function show(cell: ReportCell): string {
  return cell === null ? '' : String(cell)
}

/**
 * Spec sections 17 "Reports", 20 and 21: operational reports over a date
 * range, previewed here and downloadable as CSV for spreadsheets.
 */
export function ReportsPage() {
  const [name, setName] = useState<ReportName>('assignments')
  const [start, setStart] = useState(() => daysAgo(6))
  const [end, setEnd] = useState(() => isoDate(new Date()))
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const selected = REPORTS.find((r) => r.name === name)!
  // The shown report still matches the controls, so its CSV link is valid.
  const current = report?.name === name && report.start === start && report.end === end

  async function handleShow(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsLoading(true)
    try {
      setReport(await api.getReport(name, start, end))
    } catch (err) {
      setReport(null)
      setError(err instanceof ApiError ? err.message : 'Failed to load the report.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <main className="reports-page">
      <h1>Reports</h1>
      <form className="reports-controls" onSubmit={(event) => void handleShow(event)}>
        <label htmlFor="report-name">Report</label>
        <select
          id="report-name"
          value={name}
          onChange={(event) => setName(event.target.value as ReportName)}
        >
          {REPORTS.map((r) => (
            <option key={r.name} value={r.name}>
              {r.label}
            </option>
          ))}
        </select>
        <label htmlFor="report-start">From</label>
        <input
          id="report-start"
          type="date"
          value={start}
          onChange={(event) => setStart(event.target.value)}
          required
        />
        <label htmlFor="report-end">To</label>
        <input
          id="report-end"
          type="date"
          value={end}
          onChange={(event) => setEnd(event.target.value)}
          required
        />
        <button type="submit" disabled={isLoading}>
          {isLoading ? 'Loading…' : 'Show report'}
        </button>
        {selected.note && <p className="status">{selected.note}</p>}
      </form>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {report && current && (
        <section aria-labelledby="report-title">
          <h2 id="report-title">
            {report.title}: {report.start} to {report.end}
          </h2>
          <dl className="report-summary">
            {Object.entries(report.summary).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value === null ? '—' : String(value)}</dd>
              </div>
            ))}
          </dl>
          <p>
            <a className="button-link" href={api.reportCsvUrl(report.name, start, end)} download>
              Download CSV ({report.total_rows} {report.total_rows === 1 ? 'row' : 'rows'})
            </a>
          </p>
          {report.total_rows === 0 ? (
            <p className="status">Nothing in this range.</p>
          ) : (
            <>
              {report.total_rows > report.rows.length && (
                <p className="status">
                  Showing the first {report.rows.length} of {report.total_rows} rows. The CSV has
                  them all.
                </p>
              )}
              <div className="report-table-wrap">
                <table>
                  <thead>
                    <tr>
                      {report.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {report.rows.map((row, i) => (
                      <tr key={i}>
                        {row.map((cell, j) => (
                          <td key={j}>{show(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      )}
    </main>
  )
}
