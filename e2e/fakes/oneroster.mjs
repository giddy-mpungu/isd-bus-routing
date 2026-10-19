#!/usr/bin/env node
/**
 * A stand-in for a district's student information system: the two OneRoster
 * 1.1 REST calls isd-bus-routing makes (services/api/src/isd_api/
 * integrations/oneroster_api.py) — an OAuth 2 client-credentials token, then
 * `GET /students` page by page. Fictional students only.
 *
 *   node e2e/fakes/oneroster.mjs [port, default 8099]
 *
 * The client id and secret it accepts are fixed and printed nowhere else;
 * they mean nothing outside a test run.
 */
import { createServer } from 'node:http'

export const CLIENT_ID = 'e2e-sis-client'
export const CLIENT_SECRET = 'e2e-sis-secret'
// The school's id in the SIS (OneRoster org sourcedId), mapped in Setup.
export const ORG = 'org-maple-valley'
const TOKEN = 'e2e-sis-token'

const STUDENTS = [
  {
    sourcedId: 'sis-0001',
    status: 'active',
    role: 'student',
    givenName: 'Riley',
    familyName: 'Synced',
    orgs: [{ sourcedId: ORG, type: 'org' }],
    grades: ['10'],
  },
  {
    sourcedId: 'sis-0002',
    status: 'active',
    role: 'student',
    givenName: 'Jamie',
    familyName: 'Rostered',
    orgs: [{ sourcedId: ORG, type: 'org' }],
    grades: ['11'],
  },
]

function json(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify(body))
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? '/', 'http://localhost')
  if (req.method === 'POST' && url.pathname === '/token') {
    const expected = 'Basic ' + Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`).toString('base64')
    if (req.headers.authorization !== expected) return json(res, 401, { error: 'invalid_client' })
    return json(res, 200, { access_token: TOKEN, token_type: 'bearer', expires_in: 3600 })
  }
  if (req.method === 'GET' && url.pathname === '/ims/oneroster/v1p1/students') {
    if (req.headers.authorization !== `Bearer ${TOKEN}`)
      return json(res, 401, { error: 'invalid_token' })
    const limit = Number(url.searchParams.get('limit') ?? 100)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    return json(res, 200, { users: STUDENTS.slice(offset, offset + limit) })
  }
  json(res, 404, { error: 'not found' })
})

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('oneroster.mjs')) {
  const port = Number(process.argv[2] ?? 8099)
  server.listen(port, '127.0.0.1', () => console.log(`fake OneRoster on http://127.0.0.1:${port}`))
}
