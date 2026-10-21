import { useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { AbsenceImport } from '../api/types'

/**
 * Spec sections 13 and 19: absences arriving from the district's HR
 * system, as its CSV export. Nothing is saved until the preview has been
 * checked; importing the same export twice changes nothing.
 */
export function AbsenceImportSection() {
  const [csv, setCsv] = useState('')
  const [preview, setPreview] = useState<AbsenceImport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  async function run(apply: boolean) {
    setError(null)
    setIsBusy(true)
    try {
      setPreview(await api.importAbsences(csv, apply))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to read the CSV.')
    } finally {
      setIsBusy(false)
    }
  }

  async function handleFile(file: File | undefined) {
    if (file) {
      setCsv(await file.text())
      setPreview(null)
    }
  }

  const importable = preview?.rows.filter((r) => r.outcome === 'created').length ?? 0

  return (
    <section className="absence-import-section">
      <h2>Absences from HR</h2>
      <p>
        Import your HR system&apos;s absence export as CSV, with a header row of{' '}
        <code>employee_id,driver,date,start,end,reason</code>. Drivers are matched by employee ID,
        or by name when only one driver has it. Dates are YYYY-MM-DD; leave start and end empty for
        the whole day, or give HH:MM (24-hour). Reasons are this system&apos;s, such as sick leave
        or training; empty means other.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          void run(false)
        }}
      >
        <label htmlFor="absence-import-file">HR export (CSV file)</label>
        <input
          id="absence-import-file"
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => void handleFile(event.target.files?.[0])}
        />
        <label htmlFor="absence-import-text">Or paste the HR export</label>
        <textarea
          id="absence-import-text"
          rows={5}
          value={csv}
          onChange={(event) => {
            setCsv(event.target.value)
            setPreview(null)
          }}
        />
        <button type="submit" disabled={isBusy || csv.trim() === ''}>
          Preview
        </button>
      </form>
      {preview && (
        <>
          <table>
            <caption>{preview.applied ? 'Imported' : 'Preview: nothing saved yet'}</caption>
            <thead>
              <tr>
                <th scope="col">Line</th>
                <th scope="col">Driver</th>
                <th scope="col">Date</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((r) => (
                <tr key={r.line}>
                  <td>{r.line}</td>
                  <td>{r.driver}</td>
                  <td>{r.date}</td>
                  <td>
                    {r.outcome}
                    {r.message ? `: ${r.message}` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!preview.applied && importable > 0 && (
            <button type="button" disabled={isBusy} onClick={() => void run(true)}>
              Import {importable} absence{importable === 1 ? '' : 's'}
            </button>
          )}
        </>
      )}
    </section>
  )
}
