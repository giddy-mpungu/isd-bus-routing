import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { FamilyMember } from '../api/types'
import { FamilyPage } from './FamilyPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getMyFamily: vi.fn(),
    updateRidership: vi.fn(),
  }
})

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

const child: FamilyMember = {
  student_id: 10,
  full_name: 'Jamie Student',
  school_name: 'Riverside Elementary',
  stop_label: 'Oak & 5th',
  service_date: today(),
  riding_am: true,
  riding_pm: true,
}

describe('FamilyPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('renders a card per linked child with school/stop and ridership state', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    render(<FamilyPage />)

    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())
    expect(screen.getByText('Riverside Elementary')).toBeInTheDocument()
    expect(screen.getByText('Stop: Oak & 5th')).toBeInTheDocument()
    expect(screen.getByText('AM: Riding')).toBeInTheDocument()
    expect(screen.getByText('PM: Riding')).toBeInTheDocument()
  })

  it('shows a friendly message when there are no linked students', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([])
    render(<FamilyPage />)

    await waitFor(() => expect(screen.getByText('No linked students found.')).toBeInTheDocument())
  })

  it('toggling AM off calls updateRidership with is_riding false and refreshes', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    vi.mocked(api.updateRidership).mockResolvedValue(undefined)
    render(<FamilyPage />)
    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Mark not riding AM' }))

    await waitFor(() =>
      expect(api.updateRidership).toHaveBeenCalledWith(10, {
        service_date: today(),
        direction: 'am',
        is_riding: false,
      }),
    )
    expect(api.getMyFamily).toHaveBeenCalledTimes(2) // initial load + reload after PATCH
  })

  it('shows an error message when the ridership update fails', async () => {
    vi.mocked(api.getMyFamily).mockResolvedValue([child])
    vi.mocked(api.updateRidership).mockRejectedValue(
      new ApiError(403, 'You can only declare ridership for your own family'),
    )
    render(<FamilyPage />)
    await waitFor(() => expect(screen.getByText('Jamie Student')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Mark not riding AM' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('your own family'))
  })
})
