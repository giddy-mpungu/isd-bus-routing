import { useCallback, useEffect, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { FamilyMember, RideDirection } from '../api/types'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export function FamilyPage() {
  const [serviceDate] = useState(today)
  const [family, setFamily] = useState<FamilyMember[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)

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

            <div className="family-leg">
              <span>AM: {member.riding_am ? 'Riding' : 'Not riding'}</span>
              <button
                type="button"
                disabled={busyKey === `${member.student_id}-am`}
                onClick={() => void handleSetRiding(member.student_id, 'am', !member.riding_am)}
              >
                {member.riding_am ? 'Mark not riding AM' : 'Mark riding AM'}
              </button>
            </div>

            <div className="family-leg">
              <span>PM: {member.riding_pm ? 'Riding' : 'Not riding'}</span>
              <button
                type="button"
                disabled={busyKey === `${member.student_id}-pm`}
                onClick={() => void handleSetRiding(member.student_id, 'pm', !member.riding_pm)}
              >
                {member.riding_pm ? 'Mark not riding PM' : 'Mark riding PM'}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
