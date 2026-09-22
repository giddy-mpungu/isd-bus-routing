import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Stop, Student } from '../api/types'
import { StopsSection } from './StopsSection'

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
