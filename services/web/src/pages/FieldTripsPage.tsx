import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  DestinationProfile,
  Driver,
  FieldTrip,
  FieldTripObservedDuration,
  Qualification,
  TripStatus,
  Vehicle,
} from '../api/types'

const TRIP_STATUSES: TripStatus[] = [
  'requested',
  'approved',
  'assigned',
  'dispatched',
  'in_progress',
  'returning',
  'completed',
]

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatDateTimeParts(isoLike: string): { date: string; time: string } {
  // departure_at/expected_return_at are naive wall-clock timestamps
  // (no timezone offset, matching the backend's minute-of-day
  // conflict-detection design) -- extracting the digits directly
  // avoids `Date` parsing them as browser-local and then re-reading
  // them back out as UTC, which would silently apply a spurious
  // timezone shift.
  const match = /(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/.exec(isoLike)
  return match ? { date: match[1], time: `${match[2]}:${match[3]}` } : { date: '', time: isoLike }
}

function formatTripWindow(departureAt: string, expectedReturnAt: string): string {
  const dep = formatDateTimeParts(departureAt)
  const ret = formatDateTimeParts(expectedReturnAt)
  if (dep.date === ret.date) {
    return `${dep.time}–${ret.time}`
  }
  // Overnight (multi-day) trip -- show the date on both ends so it's
  // clear this isn't a same-day window.
  return `${dep.date} ${dep.time} – ${ret.date} ${ret.time}`
}

export function FieldTripsPage() {
  const [departureDate, setDepartureDate] = useState(today)
  const [trips, setTrips] = useState<FieldTrip[]>([])
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [qualifications, setQualifications] = useState<Qualification[]>([])
  const [destinationProfiles, setDestinationProfiles] = useState<DestinationProfile[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const loadAll = useCallback(async (date: string) => {
    setErrorMessage(null)
    try {
      const [tripsData, driversData, vehiclesData, qualificationsData, destinationProfilesData] =
        await Promise.all([
          api.getFieldTrips(date),
          api.getDrivers(),
          api.getVehicles(),
          api.getQualifications(),
          api.getDestinationProfiles(),
        ])
      setTrips(tripsData)
      setDrivers(driversData)
      setVehicles(vehiclesData)
      setQualifications(qualificationsData)
      setDestinationProfiles(destinationProfilesData)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to load field trips.')
    }
  }, [])

  useEffect(() => {
    void loadAll(departureDate)
  }, [departureDate, loadAll])

  const driversById = new Map(drivers.map((d) => [d.id, d]))
  const vehiclesById = new Map(vehicles.map((v) => [v.id, v]))
  const activeDrivers = drivers.filter((d) => d.is_active)
  const activeVehicles = vehicles.filter((v) => v.is_active)

  // --- Add field trip ---
  const [requestingParty, setRequestingParty] = useState('')
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [destinationProfileId, setDestinationProfileId] = useState('')
  const [departureAt, setDepartureAt] = useState('')
  const [expectedReturnAt, setExpectedReturnAt] = useState('')
  const [passengerCount, setPassengerCount] = useState('0')
  const [tripContact, setTripContact] = useState('')
  const [busAssistantName, setBusAssistantName] = useState('')
  const [specialInstructions, setSpecialInstructions] = useState('')
  const [qualCodes, setQualCodes] = useState<Set<string>>(new Set())
  const [createError, setCreateError] = useState<string | null>(null)
  const [isSavingTrip, setIsSavingTrip] = useState(false)

  function toggleQual(code: string) {
    setQualCodes((prev) => {
      const next = new Set(prev)
      if (next.has(code)) {
        next.delete(code)
      } else {
        next.add(code)
      }
      return next
    })
  }

  async function handleCreateTrip(event: FormEvent) {
    event.preventDefault()
    setCreateError(null)
    setIsSavingTrip(true)
    try {
      await api.createFieldTrip({
        requesting_party: requestingParty,
        origin,
        destination,
        destination_profile_id: destinationProfileId ? Number(destinationProfileId) : undefined,
        departure_at: departureAt,
        expected_return_at: expectedReturnAt,
        passenger_count: Number(passengerCount),
        trip_contact: tripContact,
        bus_assistant_name: busAssistantName || undefined,
        special_instructions: specialInstructions || undefined,
        required_qualification_codes: Array.from(qualCodes),
      })
      setRequestingParty('')
      setOrigin('')
      setDestination('')
      setDestinationProfileId('')
      setDepartureAt('')
      setExpectedReturnAt('')
      setPassengerCount('0')
      setTripContact('')
      setBusAssistantName('')
      setSpecialInstructions('')
      setQualCodes(new Set())
      setObservedDuration(null)
      await loadAll(departureDate)
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create field trip.')
    } finally {
      setIsSavingTrip(false)
    }
  }

  // --- Observed duration (spec section 20, applied to field trips) ---
  const [observedDuration, setObservedDuration] = useState<FieldTripObservedDuration | null>(null)
  const [observedDurationError, setObservedDurationError] = useState<string | null>(null)
  const [isCheckingObservedDuration, setIsCheckingObservedDuration] = useState(false)

  async function handleCheckObservedDuration() {
    setObservedDurationError(null)
    setObservedDuration(null)
    if (!destination) {
      setObservedDurationError('Enter a destination first.')
      return
    }
    setIsCheckingObservedDuration(true)
    try {
      setObservedDuration(
        await api.getFieldTripObservedDuration(
          destinationProfileId
            ? { destinationProfileId: Number(destinationProfileId) }
            : { destination },
        ),
      )
    } catch (err) {
      setObservedDurationError(
        err instanceof ApiError ? err.message : 'Failed to load observed duration.',
      )
    } finally {
      setIsCheckingObservedDuration(false)
    }
  }

  function handleUseAverageForReturn() {
    if (!departureAt || observedDuration?.average_actual_minutes == null) {
      return
    }
    const departure = new Date(departureAt)
    departure.setMinutes(
      departure.getMinutes() + Math.round(observedDuration.average_actual_minutes),
    )
    const pad = (n: number) => String(n).padStart(2, '0')
    setExpectedReturnAt(
      `${departure.getFullYear()}-${pad(departure.getMonth() + 1)}-${pad(departure.getDate())}` +
        `T${pad(departure.getHours())}:${pad(departure.getMinutes())}`,
    )
  }

  // --- Add destination profile (spec section 12.3) ---
  const [profileName, setProfileName] = useState('')
  const [profileEntrance, setProfileEntrance] = useState('')
  const [profileParking, setProfileParking] = useState('')
  const [profileTurnRestrictions, setProfileTurnRestrictions] = useState('')
  const [profileDriverNotes, setProfileDriverNotes] = useState('')
  const [profileError, setProfileError] = useState<string | null>(null)
  const [isSavingProfile, setIsSavingProfile] = useState(false)

  async function handleCreateProfile(event: FormEvent) {
    event.preventDefault()
    setProfileError(null)
    setIsSavingProfile(true)
    try {
      await api.createDestinationProfile({
        name: profileName,
        approved_entrance: profileEntrance || undefined,
        parking_notes: profileParking || undefined,
        turn_restrictions: profileTurnRestrictions || undefined,
        driver_notes: profileDriverNotes || undefined,
      })
      setProfileName('')
      setProfileEntrance('')
      setProfileParking('')
      setProfileTurnRestrictions('')
      setProfileDriverNotes('')
      await loadAll(departureDate)
    } catch (err) {
      setProfileError(err instanceof ApiError ? err.message : 'Failed to create profile.')
    } finally {
      setIsSavingProfile(false)
    }
  }

  // --- Per-trip: candidate driver/vehicle, conflict check, assign ---
  const [candidateDriverId, setCandidateDriverId] = useState<Record<number, string>>({})
  const [candidateVehicleId, setCandidateVehicleId] = useState<Record<number, string>>({})
  const [conflicts, setConflicts] = useState<Record<number, string[]>>({})
  const [conflictErrors, setConflictErrors] = useState<Record<number, string>>({})
  const [checkingTripId, setCheckingTripId] = useState<number | null>(null)
  const [assigningTripId, setAssigningTripId] = useState<number | null>(null)
  const [statusUpdatingTripId, setStatusUpdatingTripId] = useState<number | null>(null)

  async function handleCheckConflicts(trip: FieldTrip) {
    const driverId = candidateDriverId[trip.id]
    const vehicleId = candidateVehicleId[trip.id]
    setCheckingTripId(trip.id)
    setConflictErrors((prev) => ({ ...prev, [trip.id]: '' }))
    try {
      const result = await api.getFieldTripConflicts(
        trip.id,
        driverId ? Number(driverId) : undefined,
        vehicleId ? Number(vehicleId) : undefined,
      )
      setConflicts((prev) => ({ ...prev, [trip.id]: result.conflicts }))
    } catch (err) {
      setConflictErrors((prev) => ({
        ...prev,
        [trip.id]: err instanceof ApiError ? err.message : 'Failed to check conflicts.',
      }))
    } finally {
      setCheckingTripId(null)
    }
  }

  async function handleAssign(trip: FieldTrip) {
    const driverId = candidateDriverId[trip.id]
    const vehicleId = candidateVehicleId[trip.id]
    setAssigningTripId(trip.id)
    setConflictErrors((prev) => ({ ...prev, [trip.id]: '' }))
    try {
      await api.updateFieldTrip(trip.id, {
        status: 'assigned',
        assigned_driver_id: driverId ? Number(driverId) : undefined,
        assigned_vehicle_id: vehicleId ? Number(vehicleId) : undefined,
      })
      await loadAll(departureDate)
    } catch (err) {
      setConflictErrors((prev) => ({
        ...prev,
        [trip.id]: err instanceof ApiError ? err.message : 'Failed to assign field trip.',
      }))
    } finally {
      setAssigningTripId(null)
    }
  }

  // --- Delay management (spec section 12.2) ---
  const [returnDraft, setReturnDraft] = useState<Record<number, string>>({})
  const [delayImpact, setDelayImpact] = useState<Record<number, string[]>>({})
  const [delayErrors, setDelayErrors] = useState<Record<number, string>>({})
  const [updatingReturnTripId, setUpdatingReturnTripId] = useState<number | null>(null)

  async function handleUpdateReturn(trip: FieldTrip) {
    const draft = returnDraft[trip.id]
    if (!draft || draft === trip.expected_return_at.slice(0, 16)) return
    setUpdatingReturnTripId(trip.id)
    setDelayErrors((prev) => ({ ...prev, [trip.id]: '' }))
    try {
      await api.updateFieldTrip(trip.id, { expected_return_at: draft })
      // Re-evaluate straight away: which regular routes does the new
      // return time take this driver or bus away from?
      const check = await api.getFieldTripConflicts(trip.id)
      setDelayImpact((prev) => ({ ...prev, [trip.id]: check.routes_needing_cover }))
      setReturnDraft((prev) => {
        const next = { ...prev }
        delete next[trip.id]
        return next
      })
      await loadAll(departureDate)
    } catch (err) {
      setDelayErrors((prev) => ({
        ...prev,
        [trip.id]: err instanceof ApiError ? err.message : 'Failed to update the return time.',
      }))
    } finally {
      setUpdatingReturnTripId(null)
    }
  }

  async function handleSetStatus(trip: FieldTrip, status: TripStatus) {
    setStatusUpdatingTripId(trip.id)
    try {
      await api.updateFieldTrip(trip.id, { status })
      await loadAll(departureDate)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to update trip status.')
    } finally {
      setStatusUpdatingTripId(null)
    }
  }

  return (
    <main className="field-trips-page">
      <h1>Field trips</h1>
      <header className="schedule-toolbar">
        <div>
          <label htmlFor="field-trip-date">Departure date</label>
          <input
            id="field-trip-date"
            type="date"
            value={departureDate}
            onChange={(event) => setDepartureDate(event.target.value)}
          />
        </div>
      </header>

      {errorMessage && (
        <p role="alert" className="error">
          {errorMessage}
        </p>
      )}

      {trips.length === 0 && !errorMessage && (
        <p className="status">No field trips scheduled for this date.</p>
      )}

      <ul className="field-trip-list">
        {trips.map((trip) => {
          const trip_conflicts = conflicts[trip.id]
          const trip_conflict_error = conflictErrors[trip.id]
          return (
            <li key={trip.id} className="field-trip-card">
              <div className="field-trip-summary">
                {trip.requesting_party} — {trip.origin} → {trip.destination}
                {' ('}
                {formatTripWindow(trip.departure_at, trip.expected_return_at)}
                {') — '}
                {trip.passenger_count} passengers — status:
                <select
                  aria-label={`Status for field trip ${trip.id}`}
                  value={trip.status}
                  disabled={statusUpdatingTripId === trip.id}
                  onChange={(event) => void handleSetStatus(trip, event.target.value as TripStatus)}
                >
                  {TRIP_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field-trip-assignment">
                Driver:{' '}
                {trip.assigned_driver_id != null
                  ? (driversById.get(trip.assigned_driver_id)?.full_name ?? 'Unknown')
                  : 'Unassigned'}
                {' — Vehicle: '}
                {trip.assigned_vehicle_id != null
                  ? (vehiclesById.get(trip.assigned_vehicle_id)?.label ?? 'Unknown')
                  : 'Unassigned'}
              </div>
              {(trip.assigned_driver_id != null || trip.assigned_vehicle_id != null) && (
                <div className="field-trip-delay">
                  <label htmlFor={`field-trip-return-${trip.id}`}>Revised return time</label>
                  <input
                    id={`field-trip-return-${trip.id}`}
                    type="datetime-local"
                    value={returnDraft[trip.id] ?? trip.expected_return_at.slice(0, 16)}
                    onChange={(event) =>
                      setReturnDraft((prev) => ({ ...prev, [trip.id]: event.target.value }))
                    }
                  />
                  <button
                    type="button"
                    onClick={() => void handleUpdateReturn(trip)}
                    disabled={
                      !returnDraft[trip.id] ||
                      returnDraft[trip.id] === trip.expected_return_at.slice(0, 16) ||
                      updatingReturnTripId === trip.id
                    }
                  >
                    {updatingReturnTripId === trip.id ? 'Updating…' : 'Update return time'}
                  </button>
                  {delayErrors[trip.id] && (
                    <p role="alert" className="error">
                      {delayErrors[trip.id]}
                    </p>
                  )}
                  {delayImpact[trip.id] && delayImpact[trip.id].length === 0 && (
                    <p className="status">No regular routes are affected.</p>
                  )}
                  {delayImpact[trip.id] && delayImpact[trip.id].length > 0 && (
                    <div role="alert" className="field-trip-delay-impact">
                      <p>
                        These routes now need cover. They&apos;re flagged on the Schedule page for
                        that day:
                      </p>
                      <ul>
                        {delayImpact[trip.id].map((route, i) => (
                          <li key={i}>{route}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
              <div className="field-trip-assign-form">
                <label htmlFor={`field-trip-driver-${trip.id}`}>Candidate driver</label>
                <select
                  id={`field-trip-driver-${trip.id}`}
                  value={candidateDriverId[trip.id] ?? ''}
                  onChange={(event) =>
                    setCandidateDriverId((prev) => ({ ...prev, [trip.id]: event.target.value }))
                  }
                >
                  <option value="">Select a driver</option>
                  {activeDrivers.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.full_name}
                    </option>
                  ))}
                </select>
                <label htmlFor={`field-trip-vehicle-${trip.id}`}>Candidate vehicle</label>
                <select
                  id={`field-trip-vehicle-${trip.id}`}
                  value={candidateVehicleId[trip.id] ?? ''}
                  onChange={(event) =>
                    setCandidateVehicleId((prev) => ({ ...prev, [trip.id]: event.target.value }))
                  }
                >
                  <option value="">Select a vehicle</option>
                  {activeVehicles.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => void handleCheckConflicts(trip)}
                  disabled={checkingTripId === trip.id}
                >
                  {checkingTripId === trip.id ? 'Checking…' : 'Check conflicts'}
                </button>
                <button
                  type="button"
                  onClick={() => void handleAssign(trip)}
                  disabled={
                    assigningTripId === trip.id ||
                    (trip_conflicts != null && trip_conflicts.length > 0)
                  }
                >
                  {assigningTripId === trip.id ? 'Assigning…' : 'Assign'}
                </button>
                {trip_conflict_error && (
                  <p role="alert" className="error">
                    {trip_conflict_error}
                  </p>
                )}
                {trip_conflicts && trip_conflicts.length === 0 && (
                  <p className="status">No conflicts.</p>
                )}
                {trip_conflicts && trip_conflicts.length > 0 && (
                  <div role="alert">
                    <ul className="field-trip-conflicts">
                      {trip_conflicts.map((c, i) => (
                        <li key={i} className="error">
                          {c}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      <section className="add-forms">
        <div>
          <h2>Add field trip for {departureDate}</h2>
          <form onSubmit={(event) => void handleCreateTrip(event)}>
            <label htmlFor="trip-requesting-party">Requesting school/department</label>
            <input
              id="trip-requesting-party"
              type="text"
              value={requestingParty}
              onChange={(event) => setRequestingParty(event.target.value)}
              required
            />
            <label htmlFor="trip-origin">Origin</label>
            <input
              id="trip-origin"
              type="text"
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
              required
            />
            <label htmlFor="trip-destination">Destination</label>
            <input
              id="trip-destination"
              type="text"
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
              required
            />
            {destinationProfiles.length > 0 && (
              <>
                <label htmlFor="trip-destination-profile">Destination profile (optional)</label>
                <select
                  id="trip-destination-profile"
                  value={destinationProfileId}
                  onChange={(event) => setDestinationProfileId(event.target.value)}
                >
                  <option value="">None</option>
                  {destinationProfiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </>
            )}
            <label htmlFor="trip-departure">Departure</label>
            <input
              id="trip-departure"
              type="datetime-local"
              value={departureAt}
              onChange={(event) => setDepartureAt(event.target.value)}
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
                  <p className="status">No completed trips yet for this destination.</p>
                ) : (
                  <>
                    <p>
                      {observedDuration.sample_count} completed trip(s) — average{' '}
                      {observedDuration.average_actual_minutes} min, most recent{' '}
                      {observedDuration.most_recent_actual_minutes} min (
                      {observedDuration.most_recent_departure_date})
                    </p>
                    {observedDuration.average_actual_minutes != null && (
                      <button
                        type="button"
                        onClick={handleUseAverageForReturn}
                        disabled={!departureAt}
                      >
                        Use average to suggest return time
                      </button>
                    )}
                  </>
                )}
              </div>
            )}
            <label htmlFor="trip-expected-return">Expected return</label>
            <input
              id="trip-expected-return"
              type="datetime-local"
              value={expectedReturnAt}
              onChange={(event) => setExpectedReturnAt(event.target.value)}
              required
            />
            <label htmlFor="trip-passengers">Passenger count</label>
            <input
              id="trip-passengers"
              type="number"
              min="0"
              value={passengerCount}
              onChange={(event) => setPassengerCount(event.target.value)}
            />
            <label htmlFor="trip-contact">Trip contact</label>
            <input
              id="trip-contact"
              type="text"
              value={tripContact}
              onChange={(event) => setTripContact(event.target.value)}
              required
            />
            <label htmlFor="trip-bus-assistant">Bus assistant (if required)</label>
            <input
              id="trip-bus-assistant"
              type="text"
              value={busAssistantName}
              onChange={(event) => setBusAssistantName(event.target.value)}
            />
            <label htmlFor="trip-instructions">Special instructions</label>
            <input
              id="trip-instructions"
              type="text"
              value={specialInstructions}
              onChange={(event) => setSpecialInstructions(event.target.value)}
            />
            {qualifications.length > 0 && (
              <fieldset>
                <legend>Vehicle/accessibility requirements</legend>
                {qualifications.map((q) => (
                  <label key={q.id} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={qualCodes.has(q.code)}
                      onChange={() => toggleQual(q.code)}
                    />
                    {q.code}
                  </label>
                ))}
              </fieldset>
            )}
            {createError && (
              <p role="alert" className="error">
                {createError}
              </p>
            )}
            <button type="submit" disabled={isSavingTrip}>
              {isSavingTrip ? 'Saving…' : 'Add field trip'}
            </button>
          </form>
        </div>
      </section>

      <section className="destination-profiles-section">
        <h2>Destination profiles</h2>
        {destinationProfiles.length === 0 ? (
          <p className="status">No destination profiles yet.</p>
        ) : (
          <ul>
            {destinationProfiles.map((p) => (
              <li key={p.id}>
                {p.name}
                {p.approved_entrance && ` — entrance: ${p.approved_entrance}`}
                {p.parking_notes && ` — parking: ${p.parking_notes}`}
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={(event) => void handleCreateProfile(event)}>
          <label htmlFor="profile-name">Name</label>
          <input
            id="profile-name"
            type="text"
            value={profileName}
            onChange={(event) => setProfileName(event.target.value)}
            required
          />
          <label htmlFor="profile-entrance">Approved entrance</label>
          <input
            id="profile-entrance"
            type="text"
            value={profileEntrance}
            onChange={(event) => setProfileEntrance(event.target.value)}
          />
          <label htmlFor="profile-parking">Parking notes</label>
          <input
            id="profile-parking"
            type="text"
            value={profileParking}
            onChange={(event) => setProfileParking(event.target.value)}
          />
          <label htmlFor="profile-turn-restrictions">Turn restrictions</label>
          <input
            id="profile-turn-restrictions"
            type="text"
            value={profileTurnRestrictions}
            onChange={(event) => setProfileTurnRestrictions(event.target.value)}
          />
          <label htmlFor="profile-driver-notes">Driver notes</label>
          <input
            id="profile-driver-notes"
            type="text"
            value={profileDriverNotes}
            onChange={(event) => setProfileDriverNotes(event.target.value)}
          />
          {profileError && (
            <p role="alert" className="error">
              {profileError}
            </p>
          )}
          <button type="submit" disabled={isSavingProfile}>
            {isSavingProfile ? 'Saving…' : 'Add destination profile'}
          </button>
        </form>
      </section>
    </main>
  )
}
