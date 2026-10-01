import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Stop, Student } from '../api/types'
import { StopsSection } from './StopsSection'
import { findMap } from '../test/map'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, createStop: vi.fn(), updateStop: vi.fn(), deleteStop: vi.fn() }
})

const stop: Stop = { id: 1, label: 'Main St & 1st', location_lat: 29.7, location_lon: -95.4 }
const riderAtStop: Student = {
  id: 1,
  full_name: 'Ana Lopez',
  school_id: 1,
  stop_id: 1,
  default_ridership: 'rides',
}
const onChanged = vi.fn().mockResolvedValue(undefined)

describe('StopsSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    onChanged.mockResolvedValue(undefined)
  })

  it('shows every stop on the map', async () => {
    render(<StopsSection stops={[stop]} students={[]} canEdit={false} onChanged={onChanged} />)
    const map = await findMap('Stops map')
    expect(within(map).getByTitle('Main St & 1st')).toBeInTheDocument()
    expect(map).not.toHaveClass('is-pickable')
  })

  it('clicking the map fills in a new stop’s coordinates and marks the spot', async () => {
    vi.mocked(api.createStop).mockResolvedValue({ ...stop, id: 2, label: 'Oak Ave' })
    render(<StopsSection stops={[stop]} students={[]} canEdit onChanged={onChanged} />)
    const map = await findMap('Stops map')

    fireEvent.click(map, { clientX: 5, clientY: 5 })

    const lat = screen.getByLabelText('Stop latitude') as HTMLInputElement
    const lon = screen.getByLabelText('Stop longitude') as HTMLInputElement
    expect(lat.value).not.toBe('')
    expect(Number.isFinite(Number(lat.value)) && Number.isFinite(Number(lon.value))).toBe(true)
    expect(within(map).getByTitle('New stop')).toBeInTheDocument()

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Stop label'), 'Oak Ave')
    expect(within(map).getByTitle('Oak Ave')).toBeInTheDocument()
    const picked = { location_lat: Number(lat.value), location_lon: Number(lon.value) }
    await user.click(screen.getByRole('button', { name: 'Add stop' }))
    await waitFor(() =>
      expect(api.createStop).toHaveBeenCalledWith({ label: 'Oak Ave', ...picked }),
    )
  })

  it('while relocating, a map click moves that stop’s coordinates, not the new-stop form', async () => {
    render(<StopsSection stops={[stop]} students={[]} canEdit onChanged={onChanged} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Relocate' }))
    const map = await findMap('Stops map')

    fireEvent.click(map, { clientX: 5, clientY: 5 })

    const draftLat = document.getElementById('stop-edit-lat-1') as HTMLInputElement
    expect(draftLat.value).not.toBe('29.7')
    expect((document.getElementById('stop-lat') as HTMLInputElement).value).toBe('')
    expect(within(map).getByTitle('Main St & 1st (new spot)')).toBeInTheDocument()
  })

  it('relocates a stop (label and coordinates)', async () => {
    vi.mocked(api.updateStop).mockResolvedValue({
      ...stop,
      label: 'Moved',
      location_lat: 1,
      location_lon: 2,
    })
    const user = userEvent.setup()
    render(<StopsSection stops={[stop]} students={[]} canEdit onChanged={onChanged} />)

    await user.click(screen.getByRole('button', { name: 'Relocate' }))
    const editForm = screen.getByRole('button', { name: 'Save' }).closest('form') as HTMLElement
    const label = within(editForm).getByLabelText('Stop label')
    await user.clear(label)
    await user.type(label, 'Moved')
    const lat = within(editForm).getByLabelText('Stop latitude')
    await user.clear(lat)
    await user.type(lat, '1')
    const lon = within(editForm).getByLabelText('Stop longitude')
    await user.clear(lon)
    await user.type(lon, '2')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateStop).toHaveBeenCalledWith(1, {
        label: 'Moved',
        location_lat: 1,
        location_lon: 2,
      }),
    )
  })

  it('deletes an unused stop', async () => {
    vi.mocked(api.deleteStop).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<StopsSection stops={[stop]} students={[]} canEdit onChanged={onChanged} />)

    await user.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(api.deleteStop).toHaveBeenCalledWith(1))
    expect(onChanged).toHaveBeenCalledTimes(1)
  })

  it('disables Delete and shows the assigned count when students use the stop', () => {
    render(<StopsSection stops={[stop]} students={[riderAtStop]} canEdit onChanged={onChanged} />)

    expect(screen.getByText(/1 student\(s\) assigned/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()
  })

  it('shows the server 409 error if delete is attempted and rejected anyway', async () => {
    vi.mocked(api.deleteStop).mockRejectedValue(
      new ApiError(409, '1 student(s) are still assigned to this stop — reassign them first'),
    )
    // Simulate a stale view where the client thought the stop was free.
    const user = userEvent.setup()
    render(<StopsSection stops={[stop]} students={[]} canEdit onChanged={onChanged} />)
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('reassign them first')
  })

  it('hides relocate/delete controls for non-admins', () => {
    render(<StopsSection stops={[stop]} students={[]} canEdit={false} onChanged={onChanged} />)
    expect(screen.queryByRole('button', { name: 'Relocate' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })
})
