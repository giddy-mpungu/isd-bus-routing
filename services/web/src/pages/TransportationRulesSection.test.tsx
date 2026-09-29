import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { TransportationRules } from '../api/types'
import { TransportationRulesSection } from './TransportationRulesSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getTransportationRules: vi.fn(), updateTransportationRules: vi.fn() }
})

const defaults: TransportationRules = {
  eligibility_miles: 2,
  walk_miles: { prek: 0.25, elementary: 0.25, middle: 0.5, high: 0.5, specialized: 0 },
  ride_minutes: { prek: 45, elementary: 45, middle: 60, high: 60, specialized: 60 },
  min_stop_spacing_miles: 0.1,
  band_labels: {
    prek: 'Pre-K',
    elementary: 'Elementary (K-5)',
    middle: 'Middle (6-8)',
    high: 'High (9-12)',
    specialized: 'Specialized transportation',
  },
  is_default: true,
}

describe('TransportationRulesSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getTransportationRules).mockResolvedValue(defaults)
  })

  it('shows the defaults and saves changed limits as numbers', async () => {
    vi.mocked(api.updateTransportationRules).mockResolvedValue({ ...defaults, is_default: false })
    render(<TransportationRulesSection canEdit />)
    expect(await screen.findByText(/Using the district defaults/)).toBeInTheDocument()
    expect(screen.getByLabelText('High (9-12) walk (miles)')).toHaveValue(0.5)

    const user = userEvent.setup()
    const ride = screen.getByLabelText('Elementary (K-5) ride (minutes)')
    await user.clear(ride)
    await user.type(ride, '40')
    const spacing = screen.getByLabelText('Minimum spacing between stops (miles)')
    expect(spacing).toHaveValue(0.1)
    await user.clear(spacing)
    await user.type(spacing, '0.2')
    await user.click(screen.getByRole('button', { name: 'Save limits' }))

    await waitFor(() =>
      expect(api.updateTransportationRules).toHaveBeenCalledWith({
        eligibility_miles: 2,
        walk_miles: defaults.walk_miles,
        ride_minutes: { ...defaults.ride_minutes, elementary: 40 },
        min_stop_spacing_miles: 0.2,
      }),
    )
    expect(await screen.findByText('Rules saved.')).toBeInTheDocument()
  })

  it('is read-only for dispatchers', async () => {
    render(<TransportationRulesSection canEdit={false} />)
    expect(await screen.findByLabelText('Bus-eligible from (miles from school)')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save limits' })).not.toBeInTheDocument()
  })

  it('shows a save error', async () => {
    vi.mocked(api.updateTransportationRules).mockRejectedValue(
      new ApiError(422, 'walk_miles.high must be between 0 and 5'),
    )
    render(<TransportationRulesSection canEdit />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Save limits' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('between 0 and 5')
  })
})
