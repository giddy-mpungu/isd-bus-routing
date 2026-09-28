// Builds the web app's Content-Security-Policy from the same build args the
// bundle is built with (VITE_API_BASE_URL, VITE_MAP_TILE_URL), so the policy
// can never drift from what the app actually loads. services/web/Dockerfile
// runs this during the image build and nginx sends the result; the Caddyfile
// adds the rest of the security headers. See docs/deployment.md, "Security
// headers".
//
//   node scripts/csp.mjs   # prints an nginx add_header line
import { pathToFileURL } from 'node:url'

// Keep in sync with the fallback in src/components/MapView.tsx.
export const DEFAULT_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'

const SUBDOMAIN = 'leaflet-subdomain-placeholder'
// Scheme, optional leading wildcard label, host, optional port. Nothing else
// can reach the header, so a malformed value can't inject a directive.
const SAFE_SOURCE = /^https?:\/\/(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)*(:\d+)?$/

/**
 * The CSP source expression for a URL the app fetches from, or null when the
 * URL is a same-origin path already covered by 'self'. Leaflet's `{s}`
 * subdomain placeholder becomes a `*.` wildcard.
 * @param {string | undefined} url
 * @param {string} name the build arg, for error messages
 * @returns {string | null}
 */
export function sourceFor(url, name) {
  const value = (url ?? '').trim()
  if (value === '' || (value.startsWith('/') && !value.startsWith('//'))) return null

  let parsed
  try {
    parsed = new URL(value.replace('{s}', SUBDOMAIN))
  } catch {
    throw new Error(`${name} must be an absolute http(s) URL or a /path, got: ${value}`)
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new Error(`${name} must use https (or http), got: ${value}`)
  }
  let host = parsed.host
  if (host.startsWith(`${SUBDOMAIN}.`)) {
    host = `*.${host.slice(SUBDOMAIN.length + 1)}`
  } else if (host.includes(SUBDOMAIN)) {
    throw new Error(`${name}: {s} is only supported as the first part of the host, got: ${value}`)
  }
  const source = `${parsed.protocol}//${host}`
  if (!SAFE_SOURCE.test(source)) {
    throw new Error(`${name} has a host that can't be used in a CSP, got: ${value}`)
  }
  return source
}

/**
 * @param {{ apiBaseUrl?: string, tileUrl?: string }} options
 * @returns {string}
 */
export function buildCsp({ apiBaseUrl, tileUrl }) {
  const tiles = sourceFor(tileUrl || DEFAULT_TILE_URL, 'VITE_MAP_TILE_URL')
  const api = sourceFor(apiBaseUrl, 'VITE_API_BASE_URL')
  const directives = [
    "default-src 'self'",
    "script-src 'self'",
    // Leaflet and React only set styles through the CSSOM, which CSP
    // allows, so no 'unsafe-inline'.
    "style-src 'self'",
    // data: for the small images Vite inlines into the bundle.
    ['img-src', "'self'", 'data:', tiles],
    ['connect-src', "'self'", api],
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ]
  return directives
    .map((d) => (Array.isArray(d) ? [...new Set(d.filter(Boolean))].join(' ') : d))
    .join('; ')
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const csp = buildCsp({
    apiBaseUrl: process.env.VITE_API_BASE_URL,
    tileUrl: process.env.VITE_MAP_TILE_URL,
  })
  // "always" so error responses (404s from try_files misses, etc.) carry it too.
  process.stdout.write(`add_header Content-Security-Policy "${csp}" always;\n`)
}
