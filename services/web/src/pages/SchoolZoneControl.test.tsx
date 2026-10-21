import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { axeViolations } from '../test/axe'
import { SchoolZoneControl } from './SchoolZoneControl'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, setSchoolZone: vi.fn(), removeSchoolZone: vi.fn() }
})

const school = { id: 3, name: 'Riverside', location_lat: 29.7, location_lon: -95.4 }
const polygon = {
  type: 'Polygon',
  coordinates: [
    [
      [-95.42, 29.68],
      [-95.38, 29.68],
      [-95.38, 29.72],
      [-95.42, 29.68],
    ],
  ],
}

describe('SchoolZoneControl', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  afterEach(async () => {
    expect(await axeViolations()).toEqual([])
  })

  it("uploads a school's zone from a GeoJSON file", async () => {
    vi.mocked(api.setSchoolZone).mockResolvedValue({ ...school, has_zone: true })
    const changed = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<SchoolZoneControl school={school} onChanged={changed} />)
    expect(screen.getByText(/No attendance zone/)).toBeInTheDocument()
    const file = new File([JSON.stringify(polygon)], 'riverside.geojson', {
      type: 'application/geo+json',
    })
    await user.upload(screen.getByLabelText("Upload Riverside's zone (GeoJSON)"), file)
    await waitFor(() => expect(api.setSchoolZone).toHaveBeenCalledWith(3, polygon))
    expect(changed).toHaveBeenCalled()
  })

  it("says so when the file isn't GeoJSON", async () => {
    const user = userEvent.setup()
    render(<SchoolZoneControl school={school} onChanged={vi.fn()} />)
    const file = new File(['not json'], 'zone.json', { type: 'application/json' })
    await user.upload(screen.getByLabelText("Upload Riverside's zone (GeoJSON)"), file)
    expect(await screen.findByRole('alert')).toHaveTextContent("That file isn't GeoJSON.")
    expect(api.setSchoolZone).not.toHaveBeenCalled()
  })

  it('removes a zone on file', async () => {
    vi.mocked(api.removeSchoolZone).mockResolvedValue({ ...school, has_zone: false })
    const user = userEvent.setup()
    render(<SchoolZoneControl school={{ ...school, has_zone: true }} onChanged={vi.fn()} />)
    expect(screen.getByText(/Attendance zone on file/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: "Remove Riverside's zone" }))
    await waitFor(() => expect(api.removeSchoolZone).toHaveBeenCalledWith(3))
  })
})
