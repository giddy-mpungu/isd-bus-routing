import { lazy, Suspense, type ComponentProps } from 'react'
import type { MapView as MapViewComponent } from './MapView'

// Leaflet is about a third of the app's JavaScript and only three pages
// draw a map, so it loads on first use. Drivers' tablets never fetch it.
const MapView = lazy(() => import('./MapView').then((m) => ({ default: m.MapView })))

export function LazyMapView(props: ComponentProps<typeof MapViewComponent>) {
  return (
    <Suspense
      fallback={
        <div className="map-view map-loading" style={{ height: props.height ?? 320 }}>
          Loading map…
        </div>
      }
    >
      <MapView {...props} />
    </Suspense>
  )
}
