import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { School } from '../api/types'
import { SchoolsSection } from './SchoolsSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, createSchool: vi.fn(), updateSchool: vi.fn() }
})

const school: School = {
  id: 1,
  name: 'Riverside Elementary',
  location_lat: 29.7,
  location_lon: -95.4,
}

describe('SchoolsSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('renames and moves a school', async () => {
    vi.mocked(api.updateSchool).mockResolvedValue({ ...school, name: 'Riverside Primary' })
    const onChanged = vi.fn().mockResolvedValue(undefined)
    render(<SchoolsSection schools={[school]} canEdit onChanged={onChanged} />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Edit Riverside Elementary' }))
    const name = screen.getByLabelText('School name')
    await user.clear(name)
    await user.type(name, 'Riverside Primary')
    const lat = screen.getByLabelText('School latitude')
    await user.clear(lat)
    await user.type(lat, '29.75')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateSchool).toHaveBeenCalledWith(1, {
        name: 'Riverside Primary',
        location_lat: 29.75,
        location_lon: -95.4,
      }),
    )
    expect(onChanged).toHaveBeenCalled()
    // Back to the list after saving.
    expect(screen.queryByLabelText('School name')).not.toBeInTheDocument()
  })

  it('cancelling leaves the school unchanged', async () => {
    render(<SchoolsSection schools={[school]} canEdit onChanged={vi.fn()} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit Riverside Elementary' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.updateSchool).not.toHaveBeenCalled()
    expect(screen.getByText(/Riverside Elementary \(29.7, -95.4\)/)).toBeInTheDocument()
  })

  it('shows the server error when saving fails', async () => {
    vi.mocked(api.updateSchool).mockRejectedValue(new ApiError(403, 'Not authorized'))
    render(<SchoolsSection schools={[school]} canEdit onChanged={vi.fn()} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit Riverside Elementary' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Not authorized')
  })

  it('offers no editing without edit rights', () => {
    render(<SchoolsSection schools={[school]} canEdit={false} onChanged={vi.fn()} />)
    expect(
      screen.queryByRole('button', { name: 'Edit Riverside Elementary' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add school' })).not.toBeInTheDocument()
  })
})
