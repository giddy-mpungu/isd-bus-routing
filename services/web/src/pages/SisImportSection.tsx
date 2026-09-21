import { useState, type ChangeEvent, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { School, SisImportAction, SisImportResult } from '../api/types'

// Spec section 19 / ADR 0007: the SIS is authoritative for student identity,
// name and school assignment; stops and ridership stay local. The flow is
// deliberately two-step (preview, then apply) because anything ambiguous is
// reported for a person to decide rather than guessed at.
const COUNT_LABELS: { key: SisImportAction; label: string }[] = [
  { key: 'created', label: 'to create' },
  { key: 'updated', label: 'to update' },
  { key: 'linked', label: 'to link by name' },
  { key: 'unchanged', label: 'unchanged' },
  { key: 'needs_review', label: 'need review' },
  { key: 'removal_requested', label: 'removal requests (never applied)' },
  { key: 'error', label: 'errors' },
]

export function SisImportSection({
  schools,
  onSchoolsChanged,
}: {
  schools: School[]
  onSchoolsChanged: () => Promise<void>
}) {
  // Edits only; an untouched school falls back to its saved SIS ID.
  const [mappingDrafts, setMappingDrafts] = useState<Record<number, string>>({})
  const [mappingError, setMappingError] = useState<string | null>(null)

  const [file, setFile] = useState<File | null>(null)
  const [linkByName, setLinkByName] = useState(false)
  const [result, setResult] = useState<SisImportResult | null>(null)
  // The exact file + option combination that was last previewed. Apply is
  // only offered for that same combination.
  const [previewedKey, setPreviewedKey] = useState<string | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [isWorking, setIsWorking] = useState(false)

  const draftFor = (school: School) => mappingDrafts[school.id] ?? school.external_id ?? ''

  async function handleSaveMapping(school: School) {
    setMappingError(null)
    const draft = draftFor(school).trim()
    try {
      await api.updateSchoolExternalId(school.id, draft === '' ? null : draft)
      setMappingDrafts((prev) => {
        const { [school.id]: _saved, ...rest } = prev
        return rest
      })
      await onSchoolsChanged()
    } catch (err) {
      setMappingError(err instanceof ApiError ? err.message : 'Failed to save the SIS ID.')
    }
  }

  const currentKey = file ? `${file.name}:${file.size}:${file.lastModified}:${linkByName}` : null

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null)
    setResult(null)
    setPreviewedKey(null)
    setImportError(null)
  }

  async function run(dryRun: boolean) {
    if (!file) {
      return
    }
    setImportError(null)
    setIsWorking(true)
    try {
      const response = await api.importSisStudents(file, dryRun, linkByName)
      setResult(response)
      setPreviewedKey(dryRun ? currentKey : null)
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : 'Import failed.')
    } finally {
      setIsWorking(false)
    }
  }

  function handlePreview(event: FormEvent) {
    event.preventDefault()
    void run(true)
  }

  const canApply = file !== null && currentKey === previewedKey && result?.dry_run === true

  return (
    <section className="sis-import-section">
      <h2>SIS roster import</h2>
      <p>
        Upload a OneRoster <code>users.csv</code> from your student information system. Students are
        matched by their SIS ID; name and school come from the SIS, while stops and ridership stay
        managed here. Nothing changes until you preview and then apply.
      </p>

      <h3>School SIS IDs</h3>
      <p>A student can only be placed at a school that has its SIS organization ID set.</p>
      {mappingError && (
        <p role="alert" className="error">
          {mappingError}
        </p>
      )}
      <ul>
        {schools.map((school) => (
          <li key={school.id}>
            <label htmlFor={`sis-id-${school.id}`}>SIS ID for {school.name}</label>
            <input
              id={`sis-id-${school.id}`}
              value={draftFor(school)}
              maxLength={64}
              onChange={(event) =>
                setMappingDrafts((prev) => ({ ...prev, [school.id]: event.target.value }))
              }
            />
            <button
              type="button"
              aria-label={`Save SIS ID for ${school.name}`}
              onClick={() => void handleSaveMapping(school)}
              disabled={draftFor(school).trim() === (school.external_id ?? '')}
            >
              Save
            </button>
          </li>
        ))}
      </ul>

      <h3>Import</h3>
      <form onSubmit={handlePreview}>
        <label htmlFor="sis-file">users.csv</label>
        <input id="sis-file" type="file" accept=".csv,text/csv" onChange={handleFileChange} />
        <label htmlFor="sis-link-by-name">
          <input
            id="sis-link-by-name"
            type="checkbox"
            checked={linkByName}
            onChange={(event) => setLinkByName(event.target.checked)}
          />
          Link to existing students with the same name and school
        </label>
        <button type="submit" disabled={!file || isWorking}>
          Preview import
        </button>
        <button type="button" onClick={() => void run(false)} disabled={!canApply || isWorking}>
          Apply import
        </button>
      </form>

      {importError && (
        <p role="alert" className="error">
          {importError}
        </p>
      )}

      {result && (
        <div className="sis-import-result">
          <h3>{result.dry_run ? 'Preview (nothing changed yet)' : 'Import applied'}</h3>
          <ul>
            {COUNT_LABELS.filter(({ key }) => result.counts[key] > 0).map(({ key, label }) => (
              <li key={key}>
                {result.counts[key]} {label}
              </li>
            ))}
            {result.ignored_non_student_rows > 0 && (
              <li>{result.ignored_non_student_rows} non-student rows ignored</li>
            )}
          </ul>
          {result.rows.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Line</th>
                  <th>SIS ID</th>
                  <th>Name</th>
                  <th>Result</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row) => (
                  <tr key={`${row.line}-${row.action}`}>
                    <td>{row.line}</td>
                    <td>{row.source_id ?? '—'}</td>
                    <td>{row.full_name ?? '—'}</td>
                    <td>{row.action.replace('_', ' ')}</td>
                    <td>{row.detail ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {result.rows_truncated && <p>Only the first rows are listed; the counts are complete.</p>}
        </div>
      )}
    </section>
  )
}
