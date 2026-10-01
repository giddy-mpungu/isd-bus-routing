import { vi } from 'vitest'

/**
 * Gives the page a fake `navigator.geolocation` for one test. Undo it with
 * vi.unstubAllGlobals().
 *
 * Don't stub with `{ ...navigator, geolocation }` instead: a spread copies
 * only own properties, and jsdom defines userAgent and the rest as getters
 * on the prototype. Leaflet reads navigator.userAgent when its module
 * first loads, so a map first drawn under that stub fails to import, and
 * React.lazy caches the failure for every later map in the file.
 */
export function stubGeolocation(geolocation: Partial<Geolocation>) {
  vi.stubGlobal(
    'navigator',
    new Proxy(navigator, {
      get: (target, prop) =>
        prop === 'geolocation' ? geolocation : Reflect.get(target, prop, target),
      has: (target, prop) => prop === 'geolocation' || Reflect.has(target, prop),
    }),
  )
}
