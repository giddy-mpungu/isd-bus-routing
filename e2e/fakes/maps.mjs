#!/usr/bin/env node
/**
 * Stand-ins for the two map services isd-bus-routing calls, on one port:
 *
 * - `/census/...`: the US Census geocoder's one-line address lookup
 *   (services/api/src/isd_api/integrations/census_geocoder.py). It knows
 *   the fictional addresses below and matches nothing else, like the real
 *   one with a new subdivision.
 * - `/ors/...`: OpenRouteService directions, both the turn-by-turn GeoJSON
 *   the driver's tablet shows (isd_solver/directions.py) and the plain
 *   travel times the scheduler asks for between runs (isd_solver/domain.py).
 *   Roads are straight lines at 10 m/s, each leg named after its stop
 *   number, so a test can tell the steps it sees came from here.
 *
 * `GET /requests` lists what was asked (newest last), so a test can check
 * what the system sent, for example that a road closure became an area to
 * avoid, or that only the address went to the geocoder.
 *
 *   node e2e/fakes/maps.mjs [port, default 8098]
 */
import { createServer } from 'node:http'

export const ORS_KEY = 'e2e-ors-key'

// address (as typed, case-insensitive) -> where it is
const ADDRESSES = {
  '100 test lane, houston, tx 77007': {
    matchedAddress: '100 TEST LN, HOUSTON, TX, 77007',
    x: -95.3972,
    y: 29.7718,
  },
}

const requests = []

function json(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify(body))
}

function metres([lon1, lat1], [lon2, lat2]) {
  const rad = Math.PI / 180
  const a =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2
  return 2 * 6_371_000 * Math.asin(Math.sqrt(a))
}

function legs(coordinates) {
  return coordinates.slice(1).map((to, i) => {
    const distance = Math.round(metres(coordinates[i], to))
    return { distance, duration: Math.round(distance / 10) }
  })
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = ''
    req.on('data', (chunk) => (data += chunk))
    req.on('end', () => {
      try {
        resolve(JSON.parse(data || '{}'))
      } catch {
        resolve(null)
      }
    })
  })
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://localhost')

  if (req.method === 'GET' && url.pathname === '/requests') return json(res, 200, requests)

  if (req.method === 'GET' && url.pathname === '/census/geocoder/locations/onelineaddress') {
    requests.push({ service: 'census', query: Object.fromEntries(url.searchParams) })
    const match = ADDRESSES[(url.searchParams.get('address') ?? '').trim().toLowerCase()]
    return json(res, 200, {
      result: { addressMatches: match ? [{ ...match, coordinates: match }] : [] },
    })
  }

  const ors = url.pathname.match(/^\/ors\/v2\/directions\/([\w-]+)(\/geojson)?$/)
  if (req.method === 'POST' && ors) {
    const body = await readBody(req)
    requests.push({ service: 'ors', path: url.pathname, body })
    if (req.headers.authorization !== ORS_KEY) return json(res, 403, { error: 'bad key' })
    const coordinates = body?.coordinates
    if (!Array.isArray(coordinates) || coordinates.length < 2)
      return json(res, 400, { error: 'need two coordinates' })
    const parts = legs(coordinates)
    const summary = {
      distance: parts.reduce((sum, p) => sum + p.distance, 0),
      duration: parts.reduce((sum, p) => sum + p.duration, 0),
    }
    if (!ors[2]) return json(res, 200, { routes: [{ summary }] })
    const segments = parts.map((part, i) => ({
      ...part,
      steps: [
        {
          instruction: `Drive along E2E Road ${i + 1}`,
          name: `E2E Road ${i + 1}`,
          distance: part.distance,
          duration: part.duration,
        },
        { instruction: `Arrive at stop ${i + 1}`, name: '-', distance: 0, duration: 0 },
      ],
    }))
    return json(res, 200, {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'LineString', coordinates },
          properties: { summary, segments },
        },
      ],
    })
  }

  json(res, 404, { error: 'not found' })
})

const port = Number(process.argv[2] ?? 8098)
server.listen(port, '127.0.0.1', () => console.log(`fake map services on http://127.0.0.1:${port}`))
