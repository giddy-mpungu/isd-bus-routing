import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Driver, FieldTrip, Qualification, TripStatus, Vehicle } from '../api/types'

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

function formatDateTime(isoLike: string): string {
  // departure_at/expected_return_at are naive wall-clock timestamps
  // (no timezone offset, matching the backend's minute-of-day
  // conflict-detection design) -- extracting the digits directly
  // avoids `Date` parsing them as browser-local and then re-reading
  // them back out as UTC, which would silently apply a spurious
  // timezone shift.
  const match = /T(\d{2}):(\d{2})/.exec(isoLike)
  return match ? `${match[1]}:${match[2]}` : isoLike
}

export function FieldTripsPage() {
  const [departureDate, setDepartureDate] = useState(today)
  const [trips, setTrips] = useState<FieldTrip[]>([])
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [qualifications, setQualifications] = useState<Qualification[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const loadAll = useCallback(async (date: string) => {
    setErrorMessage(null)
    try {
      const [tripsData, driversData, vehiclesData, qualificationsData] = await Promise.all([
        api.getFieldTrips(date),
        api.getDrivers(),
        api.getVehicles(),
        api.getQualifications(),
      ])
      setTrips(tripsData)
      setDrivers(driversData)
      setVehicles(vehiclesData)
      setQualifications(qualificationsData)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to load field trips.')
    }
  }, [])

  useEffect(() => {
    void loadAll(departureDate)
  }, [departureDate, loadAll])

  const driversById = new Map(drivers.map((d) => [d.id, d]))
  const vehiclesById = new Map(vehicles.map((v) => [v.id, v]))

  // --- Add field trip ---
  const [requestingParty, setRequestingParty] = useState('')
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
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
      setDepartureAt('')
      setExpectedReturnAt('')
      setPassengerCount('0')
      setTripContact('')
      setBusAssistantName('')
      setSpecialInstructions('')
      setQualCodes(new Set())
      await loadAll(departureDate)
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create field trip.')
    } finally {
      setIsSavingTrip(false)
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
                {formatDateTime(trip.departure_at)}
                {'–'}
                {formatDateTime(trip.expected_return_at)}
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
                  {drivers.map((d) => (
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
                  {vehicles.map((v) => (
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
                  <ul className="field-trip-conflicts">
                    {trip_conflicts.map((c, i) => (
                      <li key={i} role="alert" className="error">
                        {c}
                      </li>
                    ))}
                  </ul>
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
            <label htmlFor="trip-departure">Departure</label>
            <input
              id="trip-departure"
              type="datetime-local"
              value={departureAt}
              onChange={(event) => setDepartureAt(event.target.value)}
              required
            />
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
    </main>
  )
}
