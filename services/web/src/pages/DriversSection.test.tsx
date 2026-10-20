import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Driver, Qualification } from '../api/types'
import { DriversSection } from './DriversSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, createDriver: vi.fn(), updateDriver: vi.fn() }
})

const cdlB: Qualification = {
  id: 1,
  code: 'CDL_B',
  kind: 'license',
  description: null,
  takes_wheelchair_position: false,
  is_active: true,
}
const driver: Driver = {
  id: 1,
  full_name: 'Jordan Driver',
  max_continuous_minutes: 480,
  license_class: 'cdl_b',
  is_active: true,
  qualifications: [cdlB],
}
const onChanged = vi.fn().mockResolvedValue(undefined)

describe('DriversSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    onChanged.mockResolvedValue(undefined)
  })

  it('deactivates and reactivates a driver', async () => {
    vi.mocked(api.updateDriver).mockResolvedValue({ ...driver, is_active: false })
    const user = userEvent.setup()
    render(
      <DriversSection drivers={[driver]} qualifications={[cdlB]} canEdit onChanged={onChanged} />,
    )

    await user.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(api.updateDriver).toHaveBeenCalledWith(1, { is_active: false }))
    expect(onChanged).toHaveBeenCalledTimes(1)
  })

  it('edits name, max continuous minutes, and qualifications', async () => {
    vi.mocked(api.updateDriver).mockResolvedValue(driver)
    const user = userEvent.setup()
    render(
      <DriversSection drivers={[driver]} qualifications={[cdlB]} canEdit onChanged={onChanged} />,
    )

    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const editForm = screen.getByRole('button', { name: 'Save' }).closest('form') as HTMLElement
    const nameInput = within(editForm).getByLabelText('Full name')
    expect(nameInput).toHaveValue('Jordan Driver')
    expect(within(editForm).getByRole('checkbox', { name: /CDL_B/ })).toBeChecked()

    await user.clear(nameInput)
    await user.type(nameInput, 'Jordan Updated')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateDriver).toHaveBeenCalledWith(1, {
        full_name: 'Jordan Updated',
        max_continuous_minutes: 480,
        license_class: 'cdl_b',
        qualification_codes: ['CDL_B'],
      }),
    )
  })

  it('shows an error when saving an edit fails', async () => {
    vi.mocked(api.updateDriver).mockRejectedValue(new ApiError(404, 'Driver not found'))
    const user = userEvent.setup()
    render(
      <DriversSection drivers={[driver]} qualifications={[cdlB]} canEdit onChanged={onChanged} />,
    )
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Driver not found')
  })

  it('cancel discards edits without calling the API', async () => {
    const user = userEvent.setup()
    render(
      <DriversSection drivers={[driver]} qualifications={[cdlB]} canEdit onChanged={onChanged} />,
    )
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(api.updateDriver).not.toHaveBeenCalled()
  })

  it('marks an inactive driver in the list', () => {
    render(
      <DriversSection
        drivers={[{ ...driver, is_active: false }]}
        qualifications={[cdlB]}
        canEdit
        onChanged={onChanged}
      />,
    )
    expect(screen.getByText(/Jordan Driver/)).toHaveTextContent('inactive')
  })

  it('hides edit/deactivate controls for non-admins', () => {
    render(
      <DriversSection
        drivers={[driver]}
        qualifications={[cdlB]}
        canEdit={false}
        onChanged={onChanged}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Deactivate' })).not.toBeInTheDocument()
  })

  it('creates a driver with a license class', async () => {
    vi.mocked(api.createDriver).mockResolvedValue({ ...driver, id: 2, license_class: 'cdl_a' })
    const user = userEvent.setup()
    render(<DriversSection drivers={[]} qualifications={[]} canEdit onChanged={onChanged} />)

    await user.type(screen.getByLabelText('Full name'), 'Casey Morgan')
    await user.selectOptions(screen.getByLabelText('License class'), 'cdl_a')
    await user.click(screen.getByRole('button', { name: 'Add driver' }))

    await waitFor(() =>
      expect(api.createDriver).toHaveBeenCalledWith(
        expect.objectContaining({ full_name: 'Casey Morgan', license_class: 'cdl_a' }),
      ),
    )
  })

  it('changes and clears a license class when editing', async () => {
    vi.mocked(api.updateDriver).mockResolvedValue(driver)
    const user = userEvent.setup()
    render(<DriversSection drivers={[driver]} qualifications={[]} canEdit onChanged={onChanged} />)
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const editForm = screen.getByRole('button', { name: 'Save' }).closest('form') as HTMLElement
    await user.selectOptions(within(editForm).getByLabelText('License class'), '')
    await user.click(within(editForm).getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateDriver).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ license_class: null }),
      ),
    )
  })

  it('shows each driver license class, and warns when none is on record', () => {
    render(
      <DriversSection
        drivers={[driver, { ...driver, id: 2, full_name: 'No Card', license_class: null }]}
        qualifications={[]}
        canEdit={false}
        onChanged={onChanged}
      />,
    )
    expect(screen.getByText(/CDL B/)).toBeInTheDocument()
    expect(screen.getByText('no license on record')).toBeInTheDocument()
  })
})
