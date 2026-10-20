import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { OptimizationSettingsSection } from './OptimizationSettingsSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getOptimizationSettings: vi.fn(),
    updateOptimizationSettings: vi.fn(),
  }
})

const defaults = {
  crews_used_weight: 1,
  deadhead_minutes_weight: 0,
  arrival_buffer_weight: 0,
  minimum_buffer_minutes: 0,
  ride_time_weight: 0,
  max_duty_minutes: null,
  break_after_minutes: null,
  break_minutes: null,
  min_rest_minutes: null,
  is_default: true,
}

describe('OptimizationSettingsSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getOptimizationSettings).mockResolvedValue(defaults)
  })

  it('shows the current weights and says defaults are in effect', async () => {
    render(<OptimizationSettingsSection canEdit />)

    expect(await screen.findByLabelText('Crews used')).toHaveValue(1)
    expect(screen.getByLabelText('Deadhead travel')).toHaveValue(0)
    expect(screen.getByLabelText('Arrival buffer')).toHaveValue(0)
    expect(screen.getByText(/defaults are in effect/)).toBeInTheDocument()
  })

  it('saves edited weights', async () => {
    vi.mocked(api.updateOptimizationSettings).mockResolvedValue({
      crews_used_weight: 100,
      deadhead_minutes_weight: 2,
      arrival_buffer_weight: 0,
      minimum_buffer_minutes: 10,
      ride_time_weight: 0,
      max_duty_minutes: null,
      break_after_minutes: null,
      break_minutes: null,
      min_rest_minutes: null,
      is_default: false,
    })
    const user = userEvent.setup()
    render(<OptimizationSettingsSection canEdit />)
    const crews = await screen.findByLabelText('Crews used')

    await user.clear(crews)
    await user.type(crews, '100')
    await user.clear(screen.getByLabelText('Deadhead travel'))
    await user.type(screen.getByLabelText('Deadhead travel'), '2')
    const buffer = screen.getByLabelText('Minimum buffer between runs (minutes)')
    await user.clear(buffer)
    await user.type(buffer, '10')
    await user.click(screen.getByRole('button', { name: 'Save settings' }))

    await waitFor(() =>
      expect(api.updateOptimizationSettings).toHaveBeenCalledWith({
        crews_used_weight: 100,
        deadhead_minutes_weight: 2,
        arrival_buffer_weight: 0,
        minimum_buffer_minutes: 10,
        ride_time_weight: 0,
        max_duty_minutes: null,
        break_after_minutes: null,
        break_minutes: null,
        min_rest_minutes: null,
      }),
    )
    expect(await screen.findByText(/apply the next time a schedule is solved/)).toBeInTheDocument()
    expect(screen.queryByText(/defaults are in effect/)).not.toBeInTheDocument()
  })

  it('sets driver work hours in hours, sent as minutes, and clears them', async () => {
    vi.mocked(api.getOptimizationSettings).mockResolvedValue({
      ...defaults,
      max_duty_minutes: 600,
      is_default: false,
    })
    vi.mocked(api.updateOptimizationSettings).mockImplementation(async (update) => ({
      ...update,
      is_default: false,
    }))
    const user = userEvent.setup()
    render(<OptimizationSettingsSection canEdit />)
    const duty = await screen.findByLabelText('Longest day on duty (hours)')
    expect(duty).toHaveValue(10)

    await user.type(screen.getByLabelText('Most work before a break (hours)'), '4.5')
    await user.type(screen.getByLabelText('Shortest break (minutes)'), '30')
    await user.type(screen.getByLabelText('Rest between days (hours)'), '10')
    await user.clear(duty)
    await user.click(screen.getByRole('button', { name: 'Save settings' }))

    await waitFor(() =>
      expect(api.updateOptimizationSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          max_duty_minutes: null,
          break_after_minutes: 270,
          break_minutes: 30,
          min_rest_minutes: 600,
        }),
      ),
    )
  })

  it('shows the API error when saving is rejected', async () => {
    vi.mocked(api.updateOptimizationSettings).mockRejectedValue(
      new ApiError(422, 'at least one objective weight must be greater than zero'),
    )
    const user = userEvent.setup()
    render(<OptimizationSettingsSection canEdit />)
    await screen.findByLabelText('Crews used')

    await user.click(screen.getByRole('button', { name: 'Save settings' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('at least one objective weight')
  })

  it('is read-only without edit permission', async () => {
    render(<OptimizationSettingsSection canEdit={false} />)

    expect(await screen.findByLabelText('Crews used')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save settings' })).not.toBeInTheDocument()
    expect(screen.getByText(/Only a transportation administrator/)).toBeInTheDocument()
  })

  it('shows a load error', async () => {
    vi.mocked(api.getOptimizationSettings).mockRejectedValue(new ApiError(403, 'Forbidden'))
    render(<OptimizationSettingsSection canEdit />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden')
  })
})
