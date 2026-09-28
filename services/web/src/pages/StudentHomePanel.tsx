import { useMemo, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { School, Student, StudentHome } from '../api/types'
import { LazyMapView } from '../components/LazyMapView'
import type { MapMarker } from '../components/mapTypes'

/**
 * Spec section 3: a student's home location, for eligibility and later for
 * placing stops. Transportation admins only; nothing here reaches
 * dispatchers, drivers or other families. An address is looked up with the
 * US Census geocoder; when it can't find it, or puts it in the wrong place,
 * the admin clicks the map to place the home by hand.
 */
export function StudentHomePanel({
  student,
  school,
  onChanged,
}: {
  student: Student
  school: School | undefined
  onChanged: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [home, setHome] = useState<StudentHome | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [address, setAddress] = useState('')
  const [pin, setPin] = useState<[number, number] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)

  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && !loaded) {
      setError(null)
      try {
        const found = await api.getStudentHome(student.id)
        setHome(found)
        setAddress(found.address)
      } catch (err) {
        // 404 just means no home on file yet.
        if (!(err instanceof ApiError && err.status === 404)) {
          setError(err instanceof ApiError ? err.message : 'Failed to load the home.')
        }
      } finally {
        setLoaded(true)
      }
    }
  }

  async function save(withPin: boolean) {
    setError(null)
    setIsBusy(true)
    try {
      const saved = await api.setStudentHome(student.id, {
        address,
        ...(withPin && pin ? { location_lat: pin[0], location_lon: pin[1] } : {}),
      })
      setHome(saved)
      setPin(null)
      await onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save the home.')
    } finally {
      setIsBusy(false)
    }
  }

  async function remove() {
    if (!window.confirm(`Remove ${student.full_name}'s home location?`)) return
    setError(null)
    setIsBusy(true)
    try {
      await api.deleteStudentHome(student.id)
      setHome(null)
      setAddress('')
      setPin(null)
      await onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to remove the home.')
    } finally {
      setIsBusy(false)
    }
  }

  const markers = useMemo<MapMarker[]>(() => {
    const list: MapMarker[] = []
    if (school) {
      list.push({
        id: 'school',
        lat: school.location_lat,
        lon: school.location_lon,
        label: school.name,
        tone: 'school',
      })
    }
    if (pin) {
      list.push({ id: 'pin', lat: pin[0], lon: pin[1], label: 'New spot', tone: 'pick' })
    } else if (home) {
      list.push({
        id: 'home',
        lat: home.location_lat,
        lon: home.location_lon,
        label: 'Home',
        tone: 'stop',
      })
    }
    return list
  }, [school, home, pin])

  const id = `student-home-${student.id}`
  return (
    <div className="guardians-panel">
      <button type="button" onClick={() => void toggle()} aria-expanded={open}>
        {open ? 'Hide home' : 'Home'}
      </button>
      {open && (
        <div className="guardians-panel-body">
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {loaded && !home && <p className="status">No home location on file.</p>}
          {home && (
            <p className="status">
              {home.source === 'census'
                ? `Census match: ${home.matched_address ?? home.address}`
                : 'Placed by hand on the map.'}
            </p>
          )}
          <label htmlFor={`${id}-address`}>Home address</label>
          <input
            id={`${id}-address`}
            value={address}
            maxLength={500}
            autoComplete="off"
            onChange={(event) => setAddress(event.target.value)}
          />
          <button
            type="button"
            disabled={isBusy || address.trim().length < 3}
            onClick={() => void save(false)}
          >
            Look up with Census
          </button>
          <p className="status">Or click the map to place the home.</p>
          <LazyMapView
            markers={markers}
            label={`Home map for ${student.full_name}`}
            onPick={(lat, lon) => setPin([lat, lon])}
            height={240}
          />
          {pin && (
            <button
              type="button"
              disabled={isBusy || address.trim().length < 3}
              onClick={() => void save(true)}
            >
              Save the placed spot
            </button>
          )}
          {home && (
            <button
              type="button"
              className="btn-danger"
              disabled={isBusy}
              onClick={() => void remove()}
            >
              Remove home
            </button>
          )}
        </div>
      )}
    </div>
  )
}
