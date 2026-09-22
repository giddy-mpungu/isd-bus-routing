import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Qualification } from '../api/types'
import { QualificationsSection } from './QualificationsSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, createQualification: vi.fn(), updateQualification: vi.fn() }
})

const qualification: Qualification = {
  id: 1,
  code: 'lift',
  kind: 'vehicle_capability',
  description: 'Wheelchair lift',
  is_active: true,
}
const onChanged = vi.fn().mockResolvedValue(undefined)

describe('QualificationsSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    onChanged.mockResolvedValue(undefined)
  })

  it('edits only the description, leaving code/kind untouched', async () => {
    vi.mocked(api.updateQualification).mockResolvedValue({
      ...qualification,
      description: 'Updated',
    })
    const user = userEvent.setup()
    render(<QualificationsSection qualifications={[qualification]} canEdit onChanged={onChanged} />)

    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const editForm = screen.getByRole('button', { name: 'Save' }).closest('form') as HTMLElement
    const input = within(editForm).getByLabelText('Description')
    expect(input).toHaveValue('Wheelchair lift')
    await user.clear(input)
    await user.type(input, 'Updated')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateQualification).toHaveBeenCalledWith(1, { description: 'Updated' }),
    )
  })

  it('deactivates and shows the inactive marker', async () => {
    vi.mocked(api.updateQualification).mockResolvedValue({ ...qualification, is_active: false })
    const user = userEvent.setup()
    render(<QualificationsSection qualifications={[qualification]} canEdit onChanged={onChanged} />)

    await user.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() =>
      expect(api.updateQualification).toHaveBeenCalledWith(1, { is_active: false }),
    )
  })

  it('shows an error when the update fails', async () => {
    vi.mocked(api.updateQualification).mockRejectedValue(new ApiError(404, 'Not found'))
    const user = userEvent.setup()
    render(<QualificationsSection qualifications={[qualification]} canEdit onChanged={onChanged} />)
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Not found')
  })

  it('hides controls for dispatcher (canEdit=false)', () => {
    render(
      <QualificationsSection
        qualifications={[qualification]}
        canEdit={false}
        onChanged={onChanged}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Deactivate' })).not.toBeInTheDocument()
  })
})
