import { useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { SisSyncRun, SisSyncStatus } from '../api/types'
import { Badge, type BadgeTone } from '../components/Badge'

const STATUS: Record<SisSyncRun['status'], { label: string; tone: BadgeTone }> = {
  running: { label: 'Running', tone: 'info' },
  ok: { label: 'Done', tone: 'success' },
  needs_attention: { label: 'Needs a look', tone: 'warning' },
  failed: { label: 'Failed', tone: 'danger' },
}

function when(iso: string): string {
  return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

function summary(run: SisSyncRun): string {
  if (run.error) return run.error
  const c = run.counts ?? {}
  const parts = [
    `${c.created ?? 0} new`,
    `${c.updated ?? 0} changed`,
    `${c.unchanged ?? 0} unchanged`,
  ]
  for (const [key, label] of [
    ['needs_review', 'to review'],
    ['removal_requested', 'removal requests'],
    ['error', 'with problems'],
  ] as const) {
    if (c[key]) parts.push(`${c[key]} ${label}`)
  }
  return parts.join(', ')
}

/**
 * The scheduled OneRoster sync (spec section 19): nightly, applying safe
 * changes and holding the rest here for review; "Sync now" runs it at once.
 */
export function SisSyncPanel() {
  const [status, setStatus] = useState<SisSyncStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSyncing, setIsSyncing] = useState(false)
  const [openRunId, setOpenRunId] = useState<number | null>(null)

  useEffect(() => {
    let current = true
    api.getSisSyncStatus().then(
      (data) => {
        if (current) setStatus(data)
      },
      (err: unknown) => {
        if (current) setError(err instanceof ApiError ? err.message : 'Failed to load the sync.')
      },
    )
    return () => {
      current = false
    }
  }, [])

  async function syncNow() {
    setError(null)
    setIsSyncing(true)
    try {
      const run = await api.syncSisNow()
      setStatus(await api.getSisSyncStatus())
      if (run.problems && run.problems.length > 0) setOpenRunId(run.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The sync failed to start.')
    } finally {
      setIsSyncing(false)
    }
  }

  return (
    <div className="sis-sync-panel">
      <h3>Scheduled sync</h3>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {status && !status.configured && (
        <p className="status">
          Not set up: the district&apos;s OneRoster connection goes in the server settings (see the
          deployment guide). Until then, import a users.csv below.
        </p>
      )}
      {status && status.configured && (
        <>
          <p>
            Every night at {status.sync_time}, the roster is read from the district&apos;s SIS. New
            students and name, school and grade changes are applied; anything that needs a person
            waits below.{' '}
            <button type="button" onClick={() => void syncNow()} disabled={isSyncing}>
              {isSyncing ? 'Syncing…' : 'Sync now'}
            </button>
          </p>
          {status.runs.length === 0 ? (
            <p className="status">No syncs yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>How</th>
                  <th>Result</th>
                  <th>What happened</th>
                  <th aria-label="Details" />
                </tr>
              </thead>
              <tbody>
                {status.runs.map((run) => (
                  <tr key={run.id}>
                    <td>{when(run.started_at)}</td>
                    <td>{run.trigger === 'scheduled' ? 'Nightly' : 'Sync now'}</td>
                    <td>
                      <Badge tone={STATUS[run.status].tone}>{STATUS[run.status].label}</Badge>
                    </td>
                    <td>
                      {summary(run)}
                      {openRunId === run.id && run.problems && run.problems.length > 0 && (
                        <ul className="sis-sync-problems">
                          {run.problems.map((p) => (
                            <li key={`${p.line}-${p.source_id ?? ''}`}>
                              <strong>{p.full_name ?? p.source_id ?? `Record ${p.line}`}</strong> (
                              {p.action.replace(/_/g, ' ')}): {p.detail}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td>
                      {run.problems && run.problems.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setOpenRunId(openRunId === run.id ? null : run.id)}
                        >
                          {openRunId === run.id ? 'Hide' : `Show ${run.problems.length}`}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  )
}
