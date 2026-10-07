import { lazy, Suspense, type ComponentProps } from 'react'
import { useTranslation } from '../i18n'
import type { MapView as MapViewComponent } from './MapView'

// Leaflet is about a third of the app's JavaScript and only three pages
// draw a map, so it loads on first use. Drivers' tablets never fetch it.
const MapView = lazy(() => import('./MapView').then((m) => ({ default: m.MapView })))

export function LazyMapView(props: ComponentProps<typeof MapViewComponent>) {
  const { t } = useTranslation()
  return (
    <Suspense
      fallback={
        <div className="map-view map-loading" style={{ height: props.height ?? 320 }}>
          {t('Loading map…')}
        </div>
      }
    >
      <MapView {...props} />
    </Suspense>
  )
}
