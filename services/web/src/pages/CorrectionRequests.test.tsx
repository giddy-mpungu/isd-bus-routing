import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { Correction } from '../api/types'
import { CorrectionRequests } from './CorrectionRequests'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getStudentCorrections: vi.fn(), requestCorrection: vi.fn() }
})

const declined: Correction = {
  id: 1,
  student_id: 4,
  student_name: 'Ana Lopez',
  requested_by: 'Pat Parent',
  created_at: '2026-10-07T14:00:00Z',
  what_is_wrong: 'Grade says 4',
  should_say: 'Grade 5',
  status: 'declined',
  decided_at: '2026-10-08T14:00:00Z',
  response: 'Grade 4 matches the school records.',
}

describe('CorrectionRequests', () => {
  beforeEach(() => vi.resetAllMocks())

  it('sends a request and lists it as waiting', async () => {
    vi.mocked(api.getStudentCorrections).mockResolvedValue([])
    vi.mocked(api.requestCorrection).mockResolvedValue({
      ...declined,
      status: 'open',
      response: null,
    })
    render(<CorrectionRequests studentId={4} firstName="Ana" />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: "Something's wrong?" }))
    await user.type(screen.getByLabelText("What's wrong in Ana's record?"), 'Grade says 4')
    await user.type(screen.getByLabelText('What should it say?'), 'Grade 5')
    await user.click(screen.getByRole('button', { name: 'Send to the transportation office' }))
    await waitFor(() =>
      expect(api.requestCorrection).toHaveBeenCalledWith(4, {
        what_is_wrong: 'Grade says 4',
        should_say: 'Grade 5',
      }),
    )
    expect(await screen.findByText('Waiting for an answer')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Sent.')
  })

  it("shows the office's answer and the right to a hearing when declined", async () => {
    vi.mocked(api.getStudentCorrections).mockResolvedValue([declined])
    render(<CorrectionRequests studentId={4} firstName="Ana" />)
    expect(await screen.findByText('Declined')).toBeInTheDocument()
    expect(screen.getByText(/Grade 4 matches the school records\./)).toBeInTheDocument()
    expect(screen.getByText(/ask the district for a hearing/)).toBeInTheDocument()
  })
})
