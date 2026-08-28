import { useCallback, useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Assignment, Crew, Driver, Run, School, Vehicle } from '../api/types'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatMinuteOfDay(minute: number): string {
  const hours = Math.floor(minute / 60)
  const mins = minute % 60
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`
}

export function SchedulePage() {
  const [serviceDate, setServiceDate] = useState(today)
  const [runs, setRuns] = useState<Run[]>([])
  const [crews, setCrews] = useState<Crew[]>([])
  const [schools, setSchools] = useState<School[]>([])
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  const loadAll = useCallback(async (date: string) => {
    setErrorMessage(null)
    try {
      const [runsData, crewsData, schoolsData, driversData, vehiclesData, assignmentsData] =
        await Promise.all([
          api.getRuns(date),
          api.getCrews(date),
          api.getSchools(),
          api.getDrivers(),
          api.getVehicles(),
          api.getAssignments(date),
        ])
      setRuns(runsData)
      setCrews(crewsData)
      setSchools(schoolsData)
      setDrivers(driversData)
      setVehicles(vehiclesData)
      setAssignments(assignmentsData)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to load schedule data.')
    }
  }, [])

  useEffect(() => {
    void loadAll(serviceDate)
  }, [serviceDate, loadAll])

  const schoolsById = new Map(schools.map((s) => [s.id, s]))
  const driversById = new Map(drivers.map((d) => [d.id, d]))
  const vehiclesById = new Map(vehicles.map((v) => [v.id, v]))
  const runsById = new Map(runs.map((r) => [r.id, r]))
  const crewsById = new Map(crews.map((c) => [c.id, c]))

  async function handleRunSchedule() {
    setIsBusy(true)
    setStatusMessage(null)
    setErrorMessage(null)
    try {
      const result = await api.runSchedule(serviceDate)
      setStatusMessage(`Schedule solved using ${result.crews_used} crew(s).`)
      await loadAll(serviceDate)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to run schedule.')
    } finally {
      setIsBusy(false)
    }
  }

  async function handleToggleLock(assignment: Assignment) {
    setIsBusy(true)
    setErrorMessage(null)
    try {
      await api.updateAssignment(assignment.id, { locked: !assignment.locked })
      await loadAll(serviceDate)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to update assignment.')
    } finally {
      setIsBusy(false)
    }
  }

  async function handleDelete(assignment: Assignment) {
    if (!window.confirm('Remove this assignment? This cannot be undone from here.')) {
      return
    }
    setIsBusy(true)
    setErrorMessage(null)
    try {
      await api.deleteAssignment(assignment.id)
      await loadAll(serviceDate)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to delete assignment.')
    } finally {
      setIsBusy(false)
    }
  }

  const assignedRunIds = new Set(assignments.map((a) => a.run_id))
  const unassignedRuns = runs.filter((r) => !assignedRunIds.has(r.id))

  return (
    <main className="schedule-page">
      <header className="schedule-toolbar">
        <div>
          <label htmlFor="service-date">Service date</label>
          <input
            id="service-date"
            type="date"
            value={serviceDate}
            onChange={(event) => setServiceDate(event.target.value)}
          />
        </div>
        <button type="button" onClick={() => void handleRunSchedule()} disabled={isBusy}>
          {isBusy ? 'Working…' : 'Run schedule'}
        </button>
      </header>

      {statusMessage && <p className="status">{statusMessage}</p>}
      {errorMessage && (
        <p role="alert" className="error">
          {errorMessage}
        </p>
      )}

      <table>
        <thead>
          <tr>
            <th>School</th>
            <th>Window</th>
            <th>Driver</th>
            <th>Vehicle</th>
            <th>Assigned</th>
            <th>Locked</th>
            <th>Explanation</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {assignments.map((assignment) => {
            const run = runsById.get(assignment.run_id)
            const crew = crewsById.get(assignment.crew_id)
            const school = run ? schoolsById.get(run.school_id) : undefined
            const driver = crew ? driversById.get(crew.driver_id) : undefined
            const vehicle = crew ? vehiclesById.get(crew.vehicle_id) : undefined
            return (
              <tr key={assignment.id}>
                <td>{school?.name ?? `School #${run?.school_id ?? '?'}`}</td>
                <td>
                  {run
                    ? `${formatMinuteOfDay(run.window_earliest)}–${formatMinuteOfDay(run.window_latest)}`
                    : '—'}
                </td>
                <td>{driver?.full_name ?? `Driver #${crew?.driver_id ?? '?'}`}</td>
                <td>{vehicle?.label ?? `Vehicle #${crew?.vehicle_id ?? '?'}`}</td>
                <td>
                  {formatMinuteOfDay(assignment.start_minute)}
                  {'–'}
                  {formatMinuteOfDay(assignment.end_minute)}
                </td>
                <td>
                  <button
                    type="button"
                    onClick={() => void handleToggleLock(assignment)}
                    disabled={isBusy}
                  >
                    {assignment.locked ? 'Unlock' : 'Lock'}
                  </button>
                </td>
                <td className="explanation">{assignment.explanation_text}</td>
                <td>
                  <button
                    type="button"
                    onClick={() => void handleDelete(assignment)}
                    disabled={isBusy}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {unassignedRuns.length > 0 && (
        <section className="unassigned">
          <h2>Runs without an assignment</h2>
          <ul>
            {unassignedRuns.map((run) => (
              <li key={run.id}>
                {schoolsById.get(run.school_id)?.name ?? `School #${run.school_id}`} (
                {formatMinuteOfDay(run.window_earliest)}
                {'–'}
                {formatMinuteOfDay(run.window_latest)})
              </li>
            ))}
          </ul>
        </section>
      )}

      {runs.length === 0 && <p>No runs exist for this date yet.</p>}
    </main>
  )
}
