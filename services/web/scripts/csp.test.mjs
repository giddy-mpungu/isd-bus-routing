import { describe, expect, it } from 'vitest'
import { buildCsp, sourceFor } from './csp.mjs'

describe('buildCsp', () => {
  it('allows only this origin plus the default OpenStreetMap tiles', () => {
    expect(buildCsp({ apiBaseUrl: '/api' })).toBe(
      "default-src 'self'; script-src 'self'; style-src 'self'; " +
        "img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; " +
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    )
  })

  it('adds a cross-origin api and a custom tile server', () => {
    const csp = buildCsp({
      apiBaseUrl: 'https://api.district.example.org/v1',
      tileUrl: 'https://{s}.tiles.example.com/{z}/{x}/{y}.png?key=abc',
    })
    expect(csp).toContain("img-src 'self' data: https://*.tiles.example.com;")
    expect(csp).toContain("connect-src 'self' https://api.district.example.org;")
  })

  it('treats a blank tile URL as the default, like MapView does', () => {
    expect(buildCsp({ tileUrl: '' })).toContain('https://tile.openstreetmap.org')
  })
})

describe('sourceFor', () => {
  it('returns null for same-origin paths', () => {
    expect(sourceFor('/api', 'X')).toBeNull()
    expect(sourceFor('/tiles/{z}/{x}/{y}.png', 'X')).toBeNull()
    expect(sourceFor(undefined, 'X')).toBeNull()
  })

  it('keeps a non-default port', () => {
    expect(sourceFor('http://localhost:8000', 'X')).toBe('http://localhost:8000')
  })

  it.each([
    'javascript:alert(1)',
    'tiles.example.com/{z}/{x}/{y}.png',
    '//tiles.example.com/{z}.png',
    'https://a.{s}.example.com/{z}.png',
    "https://evil.example.com'; script-src *",
  ])('rejects %s rather than emit a broken policy', (url) => {
    expect(() => sourceFor(url, 'VITE_MAP_TILE_URL')).toThrow(/VITE_MAP_TILE_URL/)
  })
})
