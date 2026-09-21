import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  Absence,
  AbsenceReason,
  AffectedAssignmentSubstitutes,
  Assignment,
  Crew,
  Driver,
  DriverReport,
  ExpectedRiders,
  ObservedRunDuration,
  Qualification,
  RideDirection,
  Run,
  School,
  SubstituteCandidate,
  Vehicle,
  VehiclePosition,
} from '../api/types'

const ABSENCE_REASONS: AbsenceReason[] = [
  'sick_leave',
  'personal_day',
  'vacation',
  'emergency_leave',
  'training',
  'approved_leave',
  'administrative_direction',
  'injury',
  'no_call_no_show',
  'other',
]

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatMinuteOfDay(minute: number): string {
  const hours = Math.floor(minute / 60)
  const mins = minute % 60
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`
}

function formatSecondsAgo(isoTimestamp: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(isoTimestamp).getTime()) / 1000))
  if (seconds < 60) {
    return `${seconds}s ago`
  }
  return `${Math.round(seconds / 60)}m ago`
}

export function SchedulePage() {
  const [serviceDate, setServiceDate] = useState(today)
  const [runs, setRuns] = useState<Run[]>([])
  const [crews, setCrews] = useState<Crew[]>([])
  const [schools, setSchools] = useState<School[]>([])
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [qualifications, setQualifications] = useState<Qualification[]>([])
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [absences, setAbsences] = useState<Absence[]>([])
  const [fleetPositions, setFleetPositions] = useState<VehiclePosition[]>([])
  const [driverReports, setDriverReports] = useState<DriverReport[]>([])
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  const loadAll = useCallback(async (date: string) => {
    setErrorMessage(null)
    try {
      const [
        runsData,
        crewsData,
        schoolsData,
        driversData,
        vehiclesData,
        qualificationsData,
        assignmentsData,
        absencesData,
        fleetPositionsData,
        driverReportsData,
      ] = await Promise.all([
        api.getRuns(date),
        api.getCrews(date),
        api.getSchools(),
        api.getDrivers(),
        api.getVehicles(),
        api.getQualifications(),
        api.getAssignments(date),
        api.getAbsencesForDate(date),
        api.getFleetPositions(date),
        api.getDriverReportsForDate(date),
      ])
      setRuns(runsData)
      setCrews(crewsData)
      setSchools(schoolsData)
      setDrivers(driversData)
      setVehicles(vehiclesData)
      setQualifications(qualificationsData)
      setAssignments(assignmentsData)
      setAbsences(absencesData)
      setFleetPositions(fleetPositionsData)
      setDriverReports(driverReportsData)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to load schedule data.')
    }
  }, [])

  useEffect(() => {
    void loadAll(serviceDate)
  }, [serviceDate, loadAll])

  // ADR 0009: positions are polled, not pushed -- a lightweight refresh
  // of just this one list, separate from loadAll's full reload, so the
  // dispatcher's fleet view stays roughly live without refetching
  // everything else every 20s.
  useEffect(() => {
    const intervalId = window.setInterval(() => {
      api
        .getFleetPositions(serviceDate)
        .then(setFleetPositions)
        .catch(() => undefined)
    }, 20000)
    return () => window.clearInterval(intervalId)
  }, [serviceDate])

  const schoolsById = new Map(schools.map((s) => [s.id, s]))
  const driversById = new Map(drivers.map((d) => [d.id, d]))
  const vehiclesById = new Map(vehicles.map((v) => [v.id, v]))
  const runsById = new Map(runs.map((r) => [r.id, r]))
  const vehicleQualifications = qualifications.filter((q) => q.kind === 'vehicle_capability')

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

  async function handleGenerateFromTemplates() {
    setIsBusy(true)
    setStatusMessage(null)
    setErrorMessage(null)
    try {
      const r = await api.generateFromTemplates(serviceDate)
      const parts = [
        `Generated ${r.runs_created} run(s) and ${r.crews_created} crew(s) from templates`,
      ]
      const existing = r.runs_already_existing + r.crews_already_existing
      if (existing > 0) {
        parts.push(`${existing} already existed and were left unchanged`)
      }
      if (r.crews_skipped_absent_driver_ids.length > 0) {
        const names = r.crews_skipped_absent_driver_ids.map(
          (id) => driversById.get(id)?.full_name ?? `Driver #${id}`,
        )
        parts.push(`skipped crew for absent driver(s): ${names.join(', ')}`)
      }
      setStatusMessage(`${parts.join('; ')}. Review the day, then run the schedule.`)
      await loadAll(serviceDate)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to generate from templates.')
    } finally {
      setIsBusy(false)
    }
  }

  async function handleReassignCrew(assignment: Assignment, crewId: number) {
    if (crewId === assignment.crew_id) {
      return
    }
    setIsBusy(true)
    setErrorMessage(null)
    try {
      await api.updateAssignment(assignment.id, { crew_id: crewId })
      await loadAll(serviceDate)
    } catch (err) {
      // On failure, assignments state (and so the <select>'s value) is
      // untouched — it naturally reverts to showing the original crew
      // rather than the rejected one, since this is a controlled
      // component driven by that state, not by the raw DOM selection.
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to reassign crew.')
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

  // --- Add crew (for the selected serviceDate) ---
  const [crewDriverId, setCrewDriverId] = useState('')
  const [crewVehicleId, setCrewVehicleId] = useState('')
  const [crewWindowEarliest, setCrewWindowEarliest] = useState('0')
  const [crewWindowLatest, setCrewWindowLatest] = useState('1439')
  const [crewError, setCrewError] = useState<string | null>(null)
  const [isSavingCrew, setIsSavingCrew] = useState(false)

  async function handleCreateCrew(event: FormEvent) {
    event.preventDefault()
    setCrewError(null)
    setIsSavingCrew(true)
    try {
      await api.createCrew({
        service_date: serviceDate,
        driver_id: Number(crewDriverId),
        vehicle_id: Number(crewVehicleId),
        available_window_earliest: Number(crewWindowEarliest),
        available_window_latest: Number(crewWindowLatest),
      })
      setCrewDriverId('')
      setCrewVehicleId('')
      setCrewWindowEarliest('0')
      setCrewWindowLatest('1439')
      await loadAll(serviceDate)
    } catch (err) {
      setCrewError(err instanceof ApiError ? err.message : 'Failed to create crew.')
    } finally {
      setIsSavingCrew(false)
    }
  }

  // --- Add run (for the selected serviceDate) ---
  const [runSchoolId, setRunSchoolId] = useState('')
  const [runDirection, setRunDirection] = useState<RideDirection>('am')
  const [runWindowEarliest, setRunWindowEarliest] = useState('')
  const [runWindowLatest, setRunWindowLatest] = useState('')
  const [runDuration, setRunDuration] = useState('')
  const [runBuffer, setRunBuffer] = useState('0')
  const [runPassengerCount, setRunPassengerCount] = useState('0')
  const [runQualCodes, setRunQualCodes] = useState<Set<string>>(new Set())
  const [runError, setRunError] = useState<string | null>(null)
  const [isSavingRun, setIsSavingRun] = useState(false)

  // spec §20: historical learning, decision support for duration_minutes
  // -- computed from completed assignments' actual timestamps, never
  // auto-applied (see routers/runs.py's get_observed_run_duration).
  const [observedDuration, setObservedDuration] = useState<ObservedRunDuration | null>(null)
  const [observedDurationError, setObservedDurationError] = useState<string | null>(null)
  const [isCheckingObservedDuration, setIsCheckingObservedDuration] = useState(false)

  async function handleCheckObservedDuration() {
    setObservedDurationError(null)
    setObservedDuration(null)
    if (!runSchoolId) {
      setObservedDurationError('Select a school first.')
      return
    }
    setIsCheckingObservedDuration(true)
    try {
      setObservedDuration(await api.getObservedRunDuration(Number(runSchoolId), runDirection))
    } catch (err) {
      setObservedDurationError(
        err instanceof ApiError ? err.message : 'Failed to load observed duration.',
      )
    } finally {
      setIsCheckingObservedDuration(false)
    }
  }

  function toggleRunQual(code: string) {
    setRunQualCodes((prev) => {
      const next = new Set(prev)
      if (next.has(code)) {
        next.delete(code)
      } else {
        next.add(code)
      }
      return next
    })
  }

  async function handleCreateRun(event: FormEvent) {
    event.preventDefault()
    setRunError(null)
    setIsSavingRun(true)
    try {
      await api.createRun({
        service_date: serviceDate,
        school_id: Number(runSchoolId),
        direction: runDirection,
        window_earliest: Number(runWindowEarliest),
        window_latest: Number(runWindowLatest),
        duration_minutes: Number(runDuration),
        buffer_minutes: Number(runBuffer),
        passenger_count: Number(runPassengerCount),
        required_qualification_codes: Array.from(runQualCodes),
      })
      setRunSchoolId('')
      setRunDirection('am')
      setRunWindowEarliest('')
      setRunWindowLatest('')
      setRunDuration('')
      setRunBuffer('0')
      setRunPassengerCount('0')
      setRunQualCodes(new Set())
      await loadAll(serviceDate)
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : 'Failed to create run.')
    } finally {
      setIsSavingRun(false)
    }
  }

  // --- Expected riders (decision support for passenger_count, spec
  // section 4.3 -- deliberately NOT that section's stop-sequence
  // route shortening, which needs a Route model this system doesn't
  // have; see docs/domain-model.md). Never auto-applied -- the
  // dispatcher reviews the computed count and applies it manually. ---
  const [expectedRidersRunId, setExpectedRidersRunId] = useState<number | null>(null)
  const [expectedRiders, setExpectedRiders] = useState<ExpectedRiders | null>(null)
  const [expectedRidersError, setExpectedRidersError] = useState<string | null>(null)
  const [isApplyingExpectedRiders, setIsApplyingExpectedRiders] = useState(false)

  async function handleCheckExpectedRiders(runId: number) {
    setExpectedRidersError(null)
    setExpectedRiders(null)
    setExpectedRidersRunId(runId)
    try {
      setExpectedRiders(await api.getExpectedRiders(runId))
    } catch (err) {
      setExpectedRidersError(
        err instanceof ApiError ? err.message : 'Failed to load expected riders.',
      )
    }
  }

  async function handleApplyExpectedRiders() {
    if (expectedRidersRunId == null || expectedRiders == null) {
      return
    }
    setIsApplyingExpectedRiders(true)
    setExpectedRidersError(null)
    try {
      await api.updateRun(expectedRidersRunId, {
        passenger_count: expectedRiders.expected_passenger_count,
      })
      setExpectedRidersRunId(null)
      setExpectedRiders(null)
      await loadAll(serviceDate)
    } catch (err) {
      setExpectedRidersError(
        err instanceof ApiError ? err.message : 'Failed to apply expected riders.',
      )
    } finally {
      setIsApplyingExpectedRiders(false)
    }
  }

  // --- Report absence (for the selected serviceDate) ---
  const [absenceDriverId, setAbsenceDriverId] = useState('')
  const [absenceReason, setAbsenceReason] = useState<AbsenceReason>('sick_leave')
  const [absenceWholeDay, setAbsenceWholeDay] = useState(true)
  const [absenceStartMinute, setAbsenceStartMinute] = useState('0')
  const [absenceEndMinute, setAbsenceEndMinute] = useState('1439')
  const [absenceError, setAbsenceError] = useState<string | null>(null)
  const [isSavingAbsence, setIsSavingAbsence] = useState(false)

  async function handleCreateAbsence(event: FormEvent) {
    event.preventDefault()
    setAbsenceError(null)
    setIsSavingAbsence(true)
    try {
      await api.createAbsence(Number(absenceDriverId), {
        service_date: serviceDate,
        start_minute: absenceWholeDay ? 0 : Number(absenceStartMinute),
        end_minute: absenceWholeDay ? 1439 : Number(absenceEndMinute),
        reason: absenceReason,
      })
      setAbsenceDriverId('')
      setAbsenceReason('sick_leave')
      setAbsenceWholeDay(true)
      setAbsenceStartMinute('0')
      setAbsenceEndMinute('1439')
      await loadAll(serviceDate)
    } catch (err) {
      setAbsenceError(err instanceof ApiError ? err.message : 'Failed to report absence.')
    } finally {
      setIsSavingAbsence(false)
    }
  }

  // --- Substitute candidates ---
  const [substituteDriverId, setSubstituteDriverId] = useState<number | null>(null)
  const [substituteResults, setSubstituteResults] = useState<AffectedAssignmentSubstitutes[]>([])
  const [substituteError, setSubstituteError] = useState<string | null>(null)
  const [assigningKey, setAssigningKey] = useState<string | null>(null)

  async function handleFindSubstitutes(driverId: number) {
    setSubstituteError(null)
    setSubstituteDriverId(driverId)
    try {
      setSubstituteResults(await api.getSubstituteCandidates(driverId, serviceDate))
    } catch (err) {
      setSubstituteError(err instanceof ApiError ? err.message : 'Failed to load substitutes.')
    }
  }

  async function handleAssignSubstitute(
    affected: AffectedAssignmentSubstitutes,
    candidate: SubstituteCandidate,
  ) {
    const key = `${affected.assignment_id}-${candidate.driver_id}`
    setAssigningKey(key)
    setSubstituteError(null)
    try {
      // A driver can have at most one crew per day, AND a vehicle can
      // only be on one crew per day (Crew is a driver+vehicle+date
      // triple, each side unique for that date) — the absent driver's
      // own crew row already claims the freed vehicle for this date,
      // so a candidate with no crew of their own can't be paired with
      // that vehicle via a second POST /crews (the vehicle's own
      // uniqueness constraint rejects it); repointing that existing
      // crew's driver (PATCH /crews/{id}) is the way. A candidate who
      // already has a *different* crew that date is reassigned onto
      // it via the existing PATCH .../assignments/{id} instead.
      const existingCrew = crews.find((c) => c.driver_id === candidate.driver_id)
      if (existingCrew) {
        await api.updateAssignment(affected.assignment_id, { crew_id: existingCrew.id })
      } else {
        await api.updateCrewDriver(affected.crew_id, candidate.driver_id)
      }
      await loadAll(serviceDate)
      if (substituteDriverId !== null) {
        setSubstituteResults(await api.getSubstituteCandidates(substituteDriverId, serviceDate))
      }
    } catch (err) {
      setSubstituteError(err instanceof ApiError ? err.message : 'Failed to assign substitute.')
    } finally {
      setAssigningKey(null)
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
        <button type="button" onClick={() => void handleGenerateFromTemplates()} disabled={isBusy}>
          Generate from templates
        </button>
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
            <th>Crew</th>
            <th>Assigned</th>
            <th>Locked</th>
            <th>Explanation</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {assignments.map((assignment) => {
            const run = runsById.get(assignment.run_id)
            const school = run ? schoolsById.get(run.school_id) : undefined
            return (
              <tr key={assignment.id}>
                <td>{school?.name ?? `School #${run?.school_id ?? '?'}`}</td>
                <td>
                  {run
                    ? `${formatMinuteOfDay(run.window_earliest)}–${formatMinuteOfDay(run.window_latest)}`
                    : '—'}
                </td>
                <td>
                  <select
                    aria-label="Crew"
                    value={String(assignment.crew_id)}
                    onChange={(event) =>
                      void handleReassignCrew(assignment, Number(event.target.value))
                    }
                    disabled={isBusy}
                  >
                    {crews.map((c) => {
                      const d = driversById.get(c.driver_id)
                      const v = vehiclesById.get(c.vehicle_id)
                      return (
                        <option key={c.id} value={c.id}>
                          {d?.full_name ?? `Driver #${c.driver_id}`}
                          {' — '}
                          {v?.label ?? `Vehicle #${c.vehicle_id}`}
                        </option>
                      )
                    })}
                  </select>
                </td>
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

      <section className="fleet-positions-section">
        <h2>Live fleet positions</h2>
        {fleetPositions.length === 0 ? (
          <p className="status">No vehicle has reported a position for this date yet.</p>
        ) : (
          <ul>
            {fleetPositions.map((position) => (
              <li key={position.crew_id}>
                {position.driver_full_name} — {position.vehicle_label}
                {': '}
                {position.location_lat.toFixed(5)}, {position.location_lon.toFixed(5)}
                {' ('}
                {formatSecondsAgo(position.recorded_at)}
                {')'}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="add-forms">
        <div>
          <h2>Add crew for {serviceDate}</h2>
          <form onSubmit={(event) => void handleCreateCrew(event)}>
            <label htmlFor="crew-driver">Driver</label>
            <select
              id="crew-driver"
              value={crewDriverId}
              onChange={(event) => setCrewDriverId(event.target.value)}
              required
            >
              <option value="" disabled>
                Select a driver
              </option>
              {drivers.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.full_name}
                </option>
              ))}
            </select>
            <label htmlFor="crew-vehicle">Vehicle</label>
            <select
              id="crew-vehicle"
              value={crewVehicleId}
              onChange={(event) => setCrewVehicleId(event.target.value)}
              required
            >
              <option value="" disabled>
                Select a vehicle
              </option>
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
            <label htmlFor="crew-window-earliest">Available from (minute of day)</label>
            <input
              id="crew-window-earliest"
              type="number"
              min="0"
              max="1439"
              value={crewWindowEarliest}
              onChange={(event) => setCrewWindowEarliest(event.target.value)}
              required
            />
            <label htmlFor="crew-window-latest">Available until (minute of day)</label>
            <input
              id="crew-window-latest"
              type="number"
              min="0"
              max="1439"
              value={crewWindowLatest}
              onChange={(event) => setCrewWindowLatest(event.target.value)}
              required
            />
            {crewError && (
              <p role="alert" className="error">
                {crewError}
              </p>
            )}
            <button type="submit" disabled={isSavingCrew}>
              {isSavingCrew ? 'Saving…' : 'Add crew'}
            </button>
          </form>
        </div>

        <div>
          <h2>Runs for {serviceDate}</h2>
          {runs.length === 0 ? (
            <p className="status">No runs created for this date yet.</p>
          ) : (
            <ul>
              {runs.map((run) => {
                const school = schoolsById.get(run.school_id)
                return (
                  <li key={run.id}>
                    {school?.name ?? `School #${run.school_id}`}
                    {' — '}
                    {run.direction.toUpperCase()}
                    {', '}
                    {formatMinuteOfDay(run.window_earliest)}–{formatMinuteOfDay(run.window_latest)}
                    {' — passenger_count: '}
                    {run.passenger_count}
                    <button type="button" onClick={() => void handleCheckExpectedRiders(run.id)}>
                      Check expected riders
                    </button>
                    {expectedRidersRunId === run.id && (
                      <div className="expected-riders-panel">
                        {expectedRidersError && (
                          <p role="alert" className="error">
                            {expectedRidersError}
                          </p>
                        )}
                        {expectedRiders && (
                          <>
                            <p>
                              Expected riders: {expectedRiders.expected_passenger_count}
                              {expectedRiders.riding_student_names.length > 0 &&
                                ` (${expectedRiders.riding_student_names.join(', ')})`}
                            </p>
                            {expectedRiders.ambiguous && (
                              <p role="alert" className="error">
                                Ambiguous — more than one run serves this school/date/direction, so
                                this count can&apos;t be attributed to just this run.
                              </p>
                            )}
                            <button
                              type="button"
                              onClick={() => void handleApplyExpectedRiders()}
                              disabled={expectedRiders.ambiguous || isApplyingExpectedRiders}
                            >
                              {isApplyingExpectedRiders ? 'Applying…' : 'Apply to passenger_count'}
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <div>
          <h2>Add run for {serviceDate}</h2>
          <form onSubmit={(event) => void handleCreateRun(event)}>
            <label htmlFor="run-school">School</label>
            <select
              id="run-school"
              value={runSchoolId}
              onChange={(event) => setRunSchoolId(event.target.value)}
              required
            >
              <option value="" disabled>
                Select a school
              </option>
              {schools.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <label htmlFor="run-direction">Direction</label>
            <select
              id="run-direction"
              value={runDirection}
              onChange={(event) => setRunDirection(event.target.value as RideDirection)}
            >
              <option value="am">AM</option>
              <option value="pm">PM</option>
            </select>
            <label htmlFor="run-window-earliest">Window start (minute of day)</label>
            <input
              id="run-window-earliest"
              type="number"
              min="0"
              max="1439"
              value={runWindowEarliest}
              onChange={(event) => setRunWindowEarliest(event.target.value)}
              required
            />
            <label htmlFor="run-window-latest">Window end (minute of day)</label>
            <input
              id="run-window-latest"
              type="number"
              min="0"
              max="1439"
              value={runWindowLatest}
              onChange={(event) => setRunWindowLatest(event.target.value)}
              required
            />
            <label htmlFor="run-duration">Duration (minutes)</label>
            <input
              id="run-duration"
              type="number"
              min="1"
              value={runDuration}
              onChange={(event) => setRunDuration(event.target.value)}
              required
            />
            <button
              type="button"
              onClick={() => void handleCheckObservedDuration()}
              disabled={isCheckingObservedDuration}
            >
              {isCheckingObservedDuration ? 'Checking…' : 'Check observed duration'}
            </button>
            {observedDurationError && (
              <p role="alert" className="error">
                {observedDurationError}
              </p>
            )}
            {observedDuration && (
              <div className="observed-duration-panel">
                {observedDuration.sample_count === 0 ? (
                  <p className="status">No completed runs yet for this school/direction.</p>
                ) : (
                  <>
                    <p>
                      {observedDuration.sample_count} completed run(s) — average{' '}
                      {observedDuration.average_actual_minutes} min, most recent{' '}
                      {observedDuration.most_recent_actual_minutes} min (
                      {observedDuration.most_recent_service_date})
                    </p>
                    {observedDuration.average_actual_minutes != null && (
                      <button
                        type="button"
                        onClick={() =>
                          setRunDuration(
                            String(Math.round(observedDuration.average_actual_minutes as number)),
                          )
                        }
                      >
                        Use average
                      </button>
                    )}
                  </>
                )}
              </div>
            )}
            <label htmlFor="run-buffer">Buffer (minutes)</label>
            <input
              id="run-buffer"
              type="number"
              min="0"
              value={runBuffer}
              onChange={(event) => setRunBuffer(event.target.value)}
            />
            <label htmlFor="run-passengers">Expected passengers</label>
            <input
              id="run-passengers"
              type="number"
              min="0"
              value={runPassengerCount}
              onChange={(event) => setRunPassengerCount(event.target.value)}
            />
            {vehicleQualifications.length > 0 && (
              <fieldset>
                <legend>Required vehicle qualifications</legend>
                {vehicleQualifications.map((q) => (
                  <label key={q.id} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={runQualCodes.has(q.code)}
                      onChange={() => toggleRunQual(q.code)}
                    />
                    {q.code}
                  </label>
                ))}
              </fieldset>
            )}
            {runError && (
              <p role="alert" className="error">
                {runError}
              </p>
            )}
            <button type="submit" disabled={isSavingRun}>
              {isSavingRun ? 'Saving…' : 'Add run'}
            </button>
          </form>
        </div>
      </section>

      <section className="driver-reports-section">
        <h2>Driver reports for {serviceDate}</h2>
        {driverReports.length === 0 ? (
          <p className="status">No incident or vehicle defect reports for this date.</p>
        ) : (
          <ul>
            {driverReports.map((r) => (
              <li key={r.id}>
                [{r.report_type.replace(/_/g, ' ')}]{' '}
                {driversById.get(r.driver_id)?.full_name ?? `Driver #${r.driver_id}`}
                {r.vehicle_id != null &&
                  ` — ${vehiclesById.get(r.vehicle_id)?.label ?? `Vehicle #${r.vehicle_id}`}`}
                {': '}
                {r.description}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="absences-section">
        <h2>Driver absences for {serviceDate}</h2>
        {absences.length === 0 && <p>No absences reported for this date.</p>}
        {absences.length > 0 && (
          <ul>
            {absences.map((absence) => (
              <li key={absence.id}>
                {driversById.get(absence.driver_id)?.full_name ?? `Driver #${absence.driver_id}`}
                {' — '}
                {absence.reason.replace(/_/g, ' ')}
                {' ('}
                {formatMinuteOfDay(absence.start_minute)}
                {'–'}
                {formatMinuteOfDay(absence.end_minute)}
                {')'}
                <button
                  type="button"
                  onClick={() => void handleFindSubstitutes(absence.driver_id)}
                  disabled={isBusy}
                >
                  Find substitutes
                </button>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={(event) => void handleCreateAbsence(event)}>
          <label htmlFor="absence-driver">Absent driver</label>
          <select
            id="absence-driver"
            value={absenceDriverId}
            onChange={(event) => setAbsenceDriverId(event.target.value)}
            required
          >
            <option value="" disabled>
              Select a driver
            </option>
            {drivers.map((d) => (
              <option key={d.id} value={d.id}>
                {d.full_name}
              </option>
            ))}
          </select>
          <label htmlFor="absence-reason">Reason</label>
          <select
            id="absence-reason"
            value={absenceReason}
            onChange={(event) => setAbsenceReason(event.target.value as AbsenceReason)}
          >
            {ABSENCE_REASONS.map((reason) => (
              <option key={reason} value={reason}>
                {reason.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={absenceWholeDay}
              onChange={(event) => setAbsenceWholeDay(event.target.checked)}
            />
            Whole day
          </label>
          {!absenceWholeDay && (
            <>
              <label htmlFor="absence-start">Start (minute of day)</label>
              <input
                id="absence-start"
                type="number"
                min="0"
                max="1439"
                value={absenceStartMinute}
                onChange={(event) => setAbsenceStartMinute(event.target.value)}
                required
              />
              <label htmlFor="absence-end">End (minute of day)</label>
              <input
                id="absence-end"
                type="number"
                min="0"
                max="1439"
                value={absenceEndMinute}
                onChange={(event) => setAbsenceEndMinute(event.target.value)}
                required
              />
            </>
          )}
          {absenceError && (
            <p role="alert" className="error">
              {absenceError}
            </p>
          )}
          <button type="submit" disabled={isSavingAbsence}>
            {isSavingAbsence ? 'Saving…' : 'Report absence'}
          </button>
        </form>

        {substituteError && (
          <p role="alert" className="error">
            {substituteError}
          </p>
        )}

        {substituteDriverId !== null && (
          <div className="substitute-results">
            <h3>
              Substitutes for{' '}
              {driversById.get(substituteDriverId)?.full_name ?? `Driver #${substituteDriverId}`}
            </h3>
            {substituteResults.length === 0 && <p>No affected assignments for this date.</p>}
            {substituteResults.map((affected) => (
              <div key={affected.assignment_id} className="affected-assignment">
                <p>
                  {affected.school_name} ({formatMinuteOfDay(affected.start_minute)}
                  {'–'}
                  {formatMinuteOfDay(affected.end_minute)}) — vehicle {affected.vehicle_label}
                </p>
                {affected.candidates.length === 0 && <p>No eligible substitutes found.</p>}
                <ul>
                  {affected.candidates.map((candidate) => {
                    const key = `${affected.assignment_id}-${candidate.driver_id}`
                    return (
                      <li key={candidate.driver_id}>
                        {candidate.full_name} (score {candidate.score}) —{' '}
                        {candidate.reasons.join('; ')}
                        <button
                          type="button"
                          onClick={() => void handleAssignSubstitute(affected, candidate)}
                          disabled={assigningKey === key}
                        >
                          {assigningKey === key ? 'Assigning…' : 'Assign as substitute'}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  )
}
