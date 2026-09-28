import { useCallback, useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Announcement, BusPosition, FamilyMember, RideDirection } from '../api/types'
import { LazyMapView } from '../components/LazyMapView'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export function FamilyPage() {
  const [serviceDate] = useState(today)
  const [family, setFamily] = useState<FamilyMember[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  // spec section 18: "approximate bus location" -- fetched on demand
  // per child/leg rather than eagerly for every family member, since
  // most legs won't have a run in progress at any given moment.
  const [busPositions, setBusPositions] = useState<Record<string, BusPosition>>({})
  const [busPositionErrors, setBusPositionErrors] = useState<Record<string, string>>({})
  const [locatingKey, setLocatingKey] = useState<string | null>(null)
  // spec section 18: "Delay notifications" / "Bus substitution notices"
  // / "Route-change notices" / "Transportation announcements" --
  // dispatcher-authored, never auto-generated (see
  // routers/announcements.py).
  const [announcements, setAnnouncements] = useState<Announcement[]>([])

  const loadFamily = useCallback(async (date: string) => {
    setErrorMessage(null)
    try {
      setFamily(await api.getMyFamily(date))
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to load family data.')
    }
  }, [])

  useEffect(() => {
    void loadFamily(serviceDate)
  }, [serviceDate, loadFamily])

  useEffect(() => {
    api
      .getMyAnnouncements()
      .then(setAnnouncements)
      .catch(() => undefined)
  }, [])

  async function handleSetRiding(studentId: number, direction: RideDirection, isRiding: boolean) {
    const key = `${studentId}-${direction}`
    setErrorMessage(null)
    setBusyKey(key)
    try {
      await api.updateRidership(studentId, {
        service_date: serviceDate,
        direction,
        is_riding: isRiding,
      })
      await loadFamily(serviceDate)
    } catch (err) {
      setErrorMessage(err instanceof ApiError ? err.message : 'Failed to update ridership.')
    } finally {
      setBusyKey(null)
    }
  }

  async function handleLocateBus(studentId: number, direction: RideDirection) {
    const key = `${studentId}-${direction}`
    setLocatingKey(key)
    setBusPositionErrors((prev) => ({ ...prev, [key]: '' }))
    try {
      const position = await api.getBusPosition(studentId, serviceDate, direction)
      setBusPositions((prev) => ({ ...prev, [key]: position }))
    } catch (err) {
      setBusPositionErrors((prev) => ({
        ...prev,
        [key]: err instanceof ApiError ? err.message : 'Failed to locate bus.',
      }))
    } finally {
      setLocatingKey(null)
    }
  }

  function renderLeg(member: FamilyMember, direction: RideDirection, isRiding: boolean) {
    const legKey = `${member.student_id}-${direction}`
    const closed = direction === 'am' ? member.am_changes_closed : member.pm_changes_closed
    const position = busPositions[legKey]
    const positionError = busPositionErrors[legKey]
    return (
      <div className="family-leg">
        <span>
          {direction.toUpperCase()}: {isRiding ? 'Riding' : 'Not riding'}
        </span>
        <button
          type="button"
          disabled={busyKey === legKey || closed != null}
          title={closed ?? undefined}
          onClick={() => void handleSetRiding(member.student_id, direction, !isRiding)}
        >
          {isRiding
            ? `Mark not riding ${direction.toUpperCase()}`
            : `Mark riding ${direction.toUpperCase()}`}
        </button>
        <button
          type="button"
          disabled={locatingKey === legKey}
          onClick={() => void handleLocateBus(member.student_id, direction)}
        >
          {locatingKey === legKey ? 'Locating…' : 'Locate bus'}
        </button>
        {closed && <p className="status family-leg-closed">{closed}</p>}
        {positionError && (
          <p role="alert" className="error">
            {positionError}
          </p>
        )}
        {position && (
          <p className="bus-position">
            {position.ambiguous &&
              "Can't show a single bus — more than one run serves this school/leg today."}
            {!position.ambiguous && !position.available && 'No live position yet.'}
            {position.available &&
              `${position.vehicle_label} was near ${position.location_lat?.toFixed(3)}, ${position.location_lon?.toFixed(3)}${
                position.recorded_at
                  ? ` at ${new Date(position.recorded_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
                  : ''
              }`}
          </p>
        )}
        {position?.available && position.location_lat != null && position.location_lon != null && (
          // Spec section 18: approximate only. The API rounds to about
          // 100 m, and the zoom stops short of street-level detail.
          <LazyMapView
            label={`Approximate location of ${position.vehicle_label}`}
            markers={[
              {
                id: 'bus',
                lat: position.location_lat,
                lon: position.location_lon,
                label: `${position.vehicle_label} (approximate)`,
                tone: 'approx',
              },
            ]}
            maxZoom={15}
            height={220}
          />
        )}
      </div>
    )
  }

  return (
    <div className="family-page">
      <h1>My family — {serviceDate}</h1>

      {announcements.length > 0 && (
        <section className="announcements-panel">
          <h2>Transportation announcements</h2>
          <ul>
            {announcements.map((a) => (
              <li key={a.id}>
                [{a.category.replace(/_/g, ' ')}] {a.message}
              </li>
            ))}
          </ul>
        </section>
      )}

      {errorMessage && (
        <p role="alert" className="error">
          {errorMessage}
        </p>
      )}
      {family.length === 0 && !errorMessage && <p className="status">No linked students found.</p>}

      <ul className="family-list">
        {family.map((member) => (
          <li key={member.student_id} className="family-card">
            <div className="family-name">{member.full_name}</div>
            <div className="family-school">{member.school_name}</div>
            <div className="family-stop">Stop: {member.stop_label ?? 'Not yet assigned'}</div>

            {renderLeg(member, 'am', member.riding_am)}
            {renderLeg(member, 'pm', member.riding_pm)}
          </li>
        ))}
      </ul>
    </div>
  )
}
