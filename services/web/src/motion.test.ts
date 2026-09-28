import { describe, expect, it } from 'vitest'
import { distanceMetres, MOVING_MPS, nextMoving, speedAt, STOPPED_MPS, type Fix } from './motion'

const at = (lat: number, lon: number, seconds: number, speed: number | null = null): Fix => ({
  lat,
  lon,
  time: seconds * 1000,
  speed,
})

describe('motion', () => {
  it('measures distance between fixes', () => {
    // 0.001 degrees of latitude is about 111 m anywhere.
    expect(distanceMetres(at(29.7, -95.4, 0), at(29.701, -95.4, 0))).toBeCloseTo(111.2, 0)
  })

  it("uses the device's own speed when it reports one", () => {
    expect(speedAt(null, at(29.7, -95.4, 0, 12.5))).toBe(12.5)
    expect(speedAt(at(29.7, -95.4, 0), at(29.8, -95.4, 10, 0))).toBe(0)
  })

  it('works speed out from two fixes when the device reports none', () => {
    expect(speedAt(at(29.7, -95.4, 0), at(29.701, -95.4, 10))).toBeCloseTo(11.1, 1)
  })

  it("can't tell from one fix, or from fixes too close together", () => {
    expect(speedAt(null, at(29.7, -95.4, 0))).toBeNull()
    expect(speedAt(at(29.7, -95.4, 0), at(29.701, -95.4, 1))).toBeNull()
    expect(speedAt(null, at(29.7, -95.4, 0, Number.NaN))).toBeNull()
  })

  it('starts moving above about 5 mph and stops only below about 2 mph', () => {
    expect(nextMoving(false, MOVING_MPS - 0.1)).toBe(false)
    expect(nextMoving(false, MOVING_MPS)).toBe(true)
    // Crawling in traffic stays "moving" rather than flickering.
    expect(nextMoving(true, 1.5)).toBe(true)
    expect(nextMoving(true, STOPPED_MPS - 0.1)).toBe(false)
  })

  it('keeps its last state when the speed is unknown', () => {
    expect(nextMoving(true, null)).toBe(true)
    expect(nextMoving(false, null)).toBe(false)
  })
})
