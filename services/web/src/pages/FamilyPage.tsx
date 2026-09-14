import { useCallback, useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { BusPosition, FamilyMember, RideDirection } from '../api/types'

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
    const position = busPositions[legKey]
    const positionError = busPositionErrors[legKey]
    return (
      <div className="family-leg">
        <span>
          {direction.toUpperCase()}: {isRiding ? 'Riding' : 'Not riding'}
        </span>
        <button
          type="button"
          disabled={busyKey === legKey}
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
              `${position.driver_full_name}, ${position.vehicle_label} — ${position.location_lat?.toFixed(5)}, ${position.location_lon?.toFixed(5)}`}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="family-page">
      <h1>My family — {serviceDate}</h1>
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
