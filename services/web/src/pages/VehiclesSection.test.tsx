import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Qualification, Vehicle } from '../api/types'
import { VehiclesSection } from './VehiclesSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, createVehicle: vi.fn(), updateVehicle: vi.fn() }
})

const lift: Qualification = {
  id: 1,
  code: 'lift',
  kind: 'vehicle_capability',
  description: null,
  takes_wheelchair_position: false,
  is_active: true,
}
const vehicle: Vehicle = {
  id: 1,
  label: 'Bus 101',
  nominal_capacity: 48,
  effective_capacity: 44,
  length_m: 10,
  width_m: 2.5,
  height_m: 3,
  weight_kg: 8000,
  vehicle_type: null,
  wheelchair_positions: null,
  turning_radius_m: null,
  required_license_class: 'cdl_b',
  is_active: true,
  qualifications: [lift],
}
const onChanged = vi.fn().mockResolvedValue(undefined)

describe('VehiclesSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    onChanged.mockResolvedValue(undefined)
  })

  it('shows inactive vehicles with a marker and offers reactivate', async () => {
    const inactive = { ...vehicle, id: 2, label: 'Bus 202', is_active: false }
    render(
      <VehiclesSection
        vehicles={[inactive]}
        qualifications={[lift]}
        canEdit
        onChanged={onChanged}
      />,
    )
    expect(screen.getByText(/Bus 202/)).toHaveTextContent('inactive')
    expect(screen.getByRole('button', { name: 'Reactivate' })).toBeInTheDocument()
  })

  it('deactivates an active vehicle', async () => {
    vi.mocked(api.updateVehicle).mockResolvedValue({ ...vehicle, is_active: false })
    const user = userEvent.setup()
    render(
      <VehiclesSection
        vehicles={[vehicle]}
        qualifications={[lift]}
        canEdit
        onChanged={onChanged}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(api.updateVehicle).toHaveBeenCalledWith(1, { is_active: false }))
    expect(onChanged).toHaveBeenCalledTimes(1)
  })

  it('opens the edit form pre-filled, edits fields and qualifications, and saves', async () => {
    vi.mocked(api.updateVehicle).mockResolvedValue(vehicle)
    const user = userEvent.setup()
    render(
      <VehiclesSection
        vehicles={[vehicle]}
        qualifications={[lift]}
        canEdit
        onChanged={onChanged}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const editForm = screen.getByRole('button', { name: 'Save' }).closest('form') as HTMLElement
    const labelInput = within(editForm).getByLabelText('Label')
    expect(labelInput).toHaveValue('Bus 101')
    expect(within(editForm).getByLabelText('Nominal capacity')).toHaveValue(48)
    const qualCheckbox = within(editForm).getByRole('checkbox', { name: /lift/ })
    expect(qualCheckbox).toBeChecked()

    await user.clear(labelInput)
    await user.type(labelInput, 'Bus 101-A')
    await user.click(qualCheckbox) // uncheck
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateVehicle).toHaveBeenCalledWith(1, {
        label: 'Bus 101-A',
        nominal_capacity: 48,
        effective_capacity: 44,
        length_m: 10,
        width_m: 2.5,
        height_m: 3,
        weight_kg: 8000,
        vehicle_type: null,
        wheelchair_positions: null,
        turning_radius_m: null,
        yard_lat: null,
        yard_lon: null,
        required_license_class: 'cdl_b',
        qualification_codes: [],
      }),
    )
    // The edit form closes after a successful save.
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
  })

  it('cancel leaves the vehicle unchanged and closes the form', async () => {
    const user = userEvent.setup()
    render(
      <VehiclesSection
        vehicles={[vehicle]}
        qualifications={[lift]}
        canEdit
        onChanged={onChanged}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const editForm = screen.getByRole('button', { name: 'Cancel' }).closest('form') as HTMLElement
    const labelInput = within(editForm).getByLabelText('Label')
    await user.clear(labelInput)
    await user.type(labelInput, 'Should not save')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(api.updateVehicle).not.toHaveBeenCalled()
    expect(screen.getByText(/Bus 101\b/)).toBeInTheDocument()
  })

  it('shows an error and keeps the form open when saving fails', async () => {
    vi.mocked(api.updateVehicle).mockRejectedValue(new ApiError(422, 'Invalid capacity'))
    const user = userEvent.setup()
    render(
      <VehiclesSection
        vehicles={[vehicle]}
        qualifications={[lift]}
        canEdit
        onChanged={onChanged}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid capacity')
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('does not offer Edit/Deactivate controls when canEdit is false', () => {
    render(
      <VehiclesSection
        vehicles={[vehicle]}
        qualifications={[lift]}
        canEdit={false}
        onChanged={onChanged}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Deactivate' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add vehicle' })).not.toBeInTheDocument()
  })

  it('only offers active vehicle-capability qualifications on the create form', () => {
    const inactiveQual: Qualification = { ...lift, id: 2, code: 'wheelchair', is_active: false }
    render(
      <VehiclesSection
        vehicles={[]}
        qualifications={[lift, inactiveQual]}
        canEdit
        onChanged={onChanged}
      />,
    )
    expect(screen.getByRole('checkbox', { name: /lift/ })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /wheelchair/ })).not.toBeInTheDocument()
  })

  it('records where a vehicle parks overnight, and shows it', async () => {
    vi.mocked(api.createVehicle).mockResolvedValue({ ...vehicle, id: 4 })
    const user = userEvent.setup()
    render(
      <VehiclesSection
        vehicles={[{ ...vehicle, yard_lat: 29.75, yard_lon: -95.45 }]}
        qualifications={[]}
        canEdit
        onChanged={onChanged}
      />,
    )
    expect(screen.getByText(/parks at 29\.7500, -95\.4500/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Label'), 'Bus 7')
    await user.type(screen.getByLabelText('Yard latitude (optional)'), '29.7')
    await user.type(screen.getByLabelText('Yard longitude (optional)'), '-95.4')
    await user.click(screen.getByRole('button', { name: 'Add vehicle' }))
    await waitFor(() =>
      expect(api.createVehicle).toHaveBeenCalledWith(
        expect.objectContaining({ label: 'Bus 7', yard_lat: 29.7, yard_lon: -95.4 }),
      ),
    )
  })

  it('lets the required license default to automatic, or be chosen', async () => {
    vi.mocked(api.createVehicle).mockResolvedValue({ ...vehicle, id: 3 })
    const user = userEvent.setup()
    render(<VehiclesSection vehicles={[]} qualifications={[]} canEdit onChanged={onChanged} />)

    await user.type(screen.getByLabelText('Label'), 'Van 9')
    await user.click(screen.getByRole('button', { name: 'Add vehicle' }))
    await waitFor(() =>
      expect(api.createVehicle).toHaveBeenCalledWith(
        expect.objectContaining({ label: 'Van 9', required_license_class: undefined }),
      ),
    )

    await user.type(screen.getByLabelText('Label'), 'Tractor')
    await user.selectOptions(screen.getByLabelText('Required license'), 'cdl_a')
    await user.click(screen.getByRole('button', { name: 'Add vehicle' }))
    await waitFor(() =>
      expect(api.createVehicle).toHaveBeenLastCalledWith(
        expect.objectContaining({ label: 'Tractor', required_license_class: 'cdl_a' }),
      ),
    )
  })

  it('shows and edits the license a vehicle needs', async () => {
    vi.mocked(api.updateVehicle).mockResolvedValue(vehicle)
    const user = userEvent.setup()
    render(
      <VehiclesSection vehicles={[vehicle]} qualifications={[]} canEdit onChanged={onChanged} />,
    )
    expect(screen.getByText(/needs CDL B/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const editForm = screen.getByRole('button', { name: 'Save' }).closest('form') as HTMLElement
    await user.selectOptions(within(editForm).getByLabelText('Required license'), 'class_c')
    await user.click(within(editForm).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(api.updateVehicle).toHaveBeenCalledWith(
        vehicle.id,
        expect.objectContaining({ required_license_class: 'class_c' }),
      ),
    )
  })
})
