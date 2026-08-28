import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { DriverAssignment } from '../api/types'
import { DriverPage } from './DriverPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getMyAssignments: vi.fn(),
    updateAssignmentStatus: vi.fn(),
  }
})

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

const assignment: DriverAssignment = {
  id: 100,
  run_id: 10,
  service_date: today(),
  school_name: 'Riverside Elementary',
  vehicle_label: 'Bus 101',
  start_minute: 360,
  end_minute: 410,
  status: 'scheduled',
  locked: false,
}

describe('DriverPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('renders a run card with resolved school/vehicle names and time window', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    render(<DriverPage />)

    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())
    expect(screen.getByText('Vehicle: Bus 101')).toBeInTheDocument()
    expect(screen.getByText('06:00 – 06:50')).toBeInTheDocument()
    expect(screen.getByText('Status: Not started')).toBeInTheDocument()
  })

  it('shows a friendly message when there are no runs today', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([])
    render(<DriverPage />)

    await waitFor(() =>
      expect(screen.getByText('No runs scheduled for today.')).toBeInTheDocument(),
    )
  })

  it('tapping Start calls the status PATCH and refreshes the card', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.updateAssignmentStatus).mockResolvedValue({
      ...assignment,
      status: 'in_progress',
    })
    render(<DriverPage />)
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Start' }))

    await waitFor(() => expect(api.updateAssignmentStatus).toHaveBeenCalledWith(100, 'in_progress'))
    expect(api.getMyAssignments).toHaveBeenCalledTimes(2) // initial load + reload after PATCH
  })

  it('tapping Complete calls the status PATCH with completed', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.updateAssignmentStatus).mockResolvedValue({ ...assignment, status: 'completed' })
    render(<DriverPage />)
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Complete' }))

    await waitFor(() => expect(api.updateAssignmentStatus).toHaveBeenCalledWith(100, 'completed'))
  })

  it('shows an error message when the status update fails', async () => {
    vi.mocked(api.getMyAssignments).mockResolvedValue([assignment])
    vi.mocked(api.updateAssignmentStatus).mockRejectedValue(new ApiError(403, 'Not your run'))
    render(<DriverPage />)
    await waitFor(() => expect(screen.getByText('Riverside Elementary')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Start' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Not your run'))
  })
})
