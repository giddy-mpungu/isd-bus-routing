import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { Correction } from '../api/types'
import { CorrectionsQueue } from './CorrectionsQueue'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getCorrections: vi.fn(), decideCorrection: vi.fn() }
})

const waiting: Correction = {
  id: 7,
  student_id: 4,
  student_name: 'Ana Lopez',
  requested_by: 'Pat Parent',
  created_at: '2026-10-07T14:00:00Z',
  what_is_wrong: 'Grade says 4',
  should_say: 'Grade 5',
  status: 'open',
  decided_at: null,
  response: null,
}

describe('CorrectionsQueue', () => {
  beforeEach(() => vi.resetAllMocks())

  it('answers a request, needing a reply first', async () => {
    vi.mocked(api.getCorrections).mockResolvedValueOnce([waiting]).mockResolvedValue([])
    vi.mocked(api.decideCorrection).mockResolvedValue({ ...waiting, status: 'declined' })
    render(<CorrectionsQueue />)
    expect(await screen.findByText('Ana Lopez')).toBeInTheDocument()
    const decline = screen.getByRole('button', { name: 'Decline' })
    expect(decline).toBeDisabled()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Answer to the family'), 'Grade 4 is right.')
    await user.click(decline)
    await waitFor(() =>
      expect(api.decideCorrection).toHaveBeenCalledWith(7, {
        decision: 'declined',
        response: 'Grade 4 is right.',
      }),
    )
    expect(await screen.findByText('No requests waiting.')).toBeInTheDocument()
  })

  it('can show answered requests too', async () => {
    vi.mocked(api.getCorrections).mockResolvedValue([])
    render(<CorrectionsQueue />)
    await userEvent.setup().click(await screen.findByLabelText('Show answered requests too'))
    await waitFor(() => expect(api.getCorrections).toHaveBeenLastCalledWith('all'))
  })
})
