import { useMemo, useState } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { DirectionsResult } from '../api/types'
import { LazyMapView } from '../components/LazyMapView'
import type { MapMarker, MapTrack } from '../components/mapTypes'
import { currentLanguage, LOCALES, useTranslation } from '../i18n'

function miles(metres: number): string {
  return `${(metres / 1609.344).toFixed(1)} mi`
}

function minutes(seconds: number): string {
  return `${Math.max(1, Math.round(seconds / 60))} min`
}

function speak(text: string) {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return
  const utterance = new SpeechSynthesisUtterance(text)
  // The server gives directions in the screen's language (OpenRouteService).
  utterance.lang = LOCALES[currentLanguage()]
  window.speechSynthesis.speak(utterance)
}

/**
 * Spec section 9: bus-specific turn-by-turn directions through the run's
 * stops today, one leg (to the next stop) at a time, in large text with
 * read-aloud. Without directions (no routing key, or the service is down)
 * it still gives the stop order and a link to open the next stop in the
 * tablet's own maps app.
 */
export function DirectionsPanel({ assignmentId }: { assignmentId: number }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [result, setResult] = useState<DirectionsResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [leg, setLeg] = useState(0)

  async function load(from?: { lat: number; lon: number }) {
    setError(null)
    setIsLoading(true)
    try {
      setResult(await api.getDirections(assignmentId, from))
      setLeg(0)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Directions failed to load.'))
    } finally {
      setIsLoading(false)
    }
  }

  function toggle() {
    const next = !open
    setOpen(next)
    if (next && result === null) void load()
  }

  function fromHere() {
    if (!('geolocation' in navigator)) return
    navigator.geolocation.getCurrentPosition(
      (p) => void load({ lat: p.coords.latitude, lon: p.coords.longitude }),
      () => setError(t("Couldn't get your position.")),
    )
  }

  const { markers, tracks } = useMemo(() => {
    if (result === null) return { markers: [] as MapMarker[], tracks: [] as MapTrack[] }
    const points: MapMarker[] = result.waypoints.map((w, i) => ({
      id: `wp-${i}`,
      lat: w.lat,
      lon: w.lon,
      label: `${i}. ${w.label}`,
      tone: i === leg + 1 ? 'pick' : 'stop',
    }))
    const line: MapTrack[] =
      result.coordinates.length > 1
        ? [
            {
              id: `directions-${assignmentId}`,
              label: t('Route'),
              points: result.coordinates.map(([lat, lon]) => [lat, lon] as [number, number]),
            },
          ]
        : []
    return { markers: points, tracks: line }
  }, [result, leg, assignmentId, t])

  const legs = result?.legs ?? []
  const current = legs[leg]
  const steps = (result?.steps ?? []).filter((s) => s.leg === leg)
  const nextWaypoint = result?.waypoints[Math.min(leg + 1, (result?.waypoints.length ?? 1) - 1)]

  return (
    <div className="directions-panel">
      <button type="button" onClick={toggle} aria-expanded={open}>
        {open ? t('Hide directions') : t('Directions')}
      </button>
      {open && (
        <div className="directions-body">
          {isLoading && <p className="status">{t('Loading directions…')}</p>}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {result && !result.available && (
            <>
              <p className="status">{result.reason}</p>
              <ol className="directions-waypoints">
                {result.waypoints.map((w, i) => (
                  <li key={`${w.label}-${i}`}>{w.label}</li>
                ))}
              </ol>
            </>
          )}
          {result && result.available && current && (
            <>
              <p className="directions-summary">
                {t('Whole route: {distance}, about {time}', {
                  distance: miles(result.distance_m),
                  time: minutes(result.duration_s),
                })}
              </p>
              <h4 className="directions-leg">
                {t('To {place} ({distance}, {time})', {
                  place: current.to_label,
                  distance: miles(current.distance_m),
                  time: minutes(current.duration_s),
                })}
              </h4>
              <ol className="directions-steps">
                {steps.map((s, i) => (
                  <li key={i}>
                    {s.instruction}
                    {s.distance_m > 0 && (
                      <span className="directions-distance"> {miles(s.distance_m)}</span>
                    )}
                  </li>
                ))}
              </ol>
              <div className="directions-actions">
                <button type="button" onClick={() => steps[0] && speak(steps[0].instruction)}>
                  <span aria-hidden="true">🔊</span> {t('Read the next instruction aloud')}
                </button>
                <button type="button" disabled={leg === 0} onClick={() => setLeg(leg - 1)}>
                  {t('Previous stop')}
                </button>
                <button
                  type="button"
                  className="driver-next-step"
                  disabled={leg >= legs.length - 1}
                  onClick={() => setLeg(leg + 1)}
                >
                  {t('Next stop')}
                </button>
              </div>
            </>
          )}
          {result && (
            <>
              {nextWaypoint && (
                <a
                  className="directions-open-maps"
                  href={`geo:${nextWaypoint.lat},${nextWaypoint.lon}?q=${nextWaypoint.lat},${nextWaypoint.lon}(${encodeURIComponent(nextWaypoint.label.replace(/[()]/g, ''))})`}
                >
                  {t('Open {place} in the maps app', { place: nextWaypoint.label })}
                </a>
              )}{' '}
              <button type="button" onClick={fromHere} disabled={isLoading}>
                {t('Route from my position')}
              </button>
              <LazyMapView
                markers={markers}
                tracks={tracks}
                label={t('Directions map for assignment {id}', { id: assignmentId })}
                height={260}
              />
              {result.available && <p className="directions-attribution">{result.attribution}</p>}
            </>
          )}
        </div>
      )}
    </div>
  )
}
