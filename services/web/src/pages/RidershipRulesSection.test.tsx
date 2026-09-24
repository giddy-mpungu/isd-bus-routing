import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { RidershipRulesSection } from './RidershipRulesSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getRidershipRules: vi.fn(), updateRidershipRules: vi.fn() }
})

const defaults = {
  timezone: 'America/Chicago',
  am_cutoff_minute: null,
  pm_cutoff_minute: null,
  is_default: true,
}

describe('RidershipRulesSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getRidershipRules).mockResolvedValue(defaults)
  })

  it('shows the district time zone and no cutoffs by default', async () => {
    render(<RidershipRulesSection canEdit />)
    expect(await screen.findByLabelText('District time zone')).toHaveValue('America/Chicago')
    expect(screen.getByLabelText('Morning ride changes close at')).toHaveValue('')
    expect(screen.getByLabelText('Afternoon ride changes close at')).toHaveValue('')
  })

  it('shows saved cutoffs as clock times', async () => {
    vi.mocked(api.getRidershipRules).mockResolvedValue({
      ...defaults,
      am_cutoff_minute: 360,
      pm_cutoff_minute: 750,
      is_default: false,
    })
    render(<RidershipRulesSection canEdit />)
    expect(await screen.findByLabelText('Morning ride changes close at')).toHaveValue('06:00')
    expect(screen.getByLabelText('Afternoon ride changes close at')).toHaveValue('12:30')
  })

  it('saves cutoffs as minutes of the day, and a blank one as none', async () => {
    vi.mocked(api.updateRidershipRules).mockResolvedValue({
      ...defaults,
      timezone: 'America/Denver',
      am_cutoff_minute: 345,
      is_default: false,
    })
    const user = userEvent.setup()
    render(<RidershipRulesSection canEdit />)
    await user.selectOptions(await screen.findByLabelText('District time zone'), 'America/Denver')
    await user.type(screen.getByLabelText('Morning ride changes close at'), '05:45')
    await user.click(screen.getByRole('button', { name: 'Save ridership rules' }))

    await waitFor(() =>
      expect(api.updateRidershipRules).toHaveBeenCalledWith({
        timezone: 'America/Denver',
        am_cutoff_minute: 345,
        pm_cutoff_minute: null,
      }),
    )
    expect(await screen.findByText('Ridership rules saved.')).toBeInTheDocument()
  })

  it('is read-only for a dispatcher', async () => {
    render(<RidershipRulesSection canEdit={false} />)
    expect(await screen.findByLabelText('District time zone')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save ridership rules' })).not.toBeInTheDocument()
  })

  it('shows the API error when saving is rejected', async () => {
    vi.mocked(api.updateRidershipRules).mockRejectedValue(new ApiError(422, 'unknown time zone'))
    const user = userEvent.setup()
    render(<RidershipRulesSection canEdit />)
    await screen.findByLabelText('District time zone')
    await user.click(screen.getByRole('button', { name: 'Save ridership rules' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('unknown time zone')
  })
})
