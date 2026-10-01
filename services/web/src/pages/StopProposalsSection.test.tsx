import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { School, Stop, StopProposal } from '../api/types'
import { StopProposalsSection } from './StopProposalsSection'
import { findMap } from '../test/map'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    generateStopProposals: vi.fn(),
    getStopProposals: vi.fn(),
    updateStopProposal: vi.fn(),
    approveStopProposal: vi.fn(),
    rejectStopProposal: vi.fn(),
  }
})

const schools: School[] = [{ id: 1, name: 'Riverside', location_lat: 29.7, location_lon: -95.4 }]
const stops: Stop[] = [{ id: 9, label: 'Oak & 5th', location_lat: 29.75, location_lon: -95.4 }]

const proposal: StopProposal = {
  id: 4,
  school_id: 1,
  kind: 'new',
  status: 'pending',
  stop_id: null,
  label: 'Proposed stop 1',
  location_lat: 29.74,
  location_lon: -95.41,
  riders: [
    { student_id: 1, full_name: 'Ana Lopez', walk_miles: 0.05, walk_limit_miles: 0.25 },
    { student_id: 2, full_name: 'Ben Ng', walk_miles: 0.3, walk_limit_miles: 0.25 },
  ],
  warnings: ['Ben Ng would walk 0.30 mi (limit 0.25 mi)'],
  created_at: '2026-09-29T12:00:00Z',
  decided_at: null,
}
const existing: StopProposal = {
  ...proposal,
  id: 5,
  kind: 'existing',
  stop_id: 9,
  label: 'Oak & 5th',
  riders: [{ student_id: 3, full_name: 'Cy Rider', walk_miles: 0.1, walk_limit_miles: 0.5 }],
  warnings: [],
}

function renderSection() {
  const onChanged = vi.fn().mockResolvedValue(undefined)
  render(<StopProposalsSection schools={schools} stops={stops} onChanged={onChanged} />)
  return onChanged
}

async function choose() {
  const user = userEvent.setup()
  await user.selectOptions(screen.getByLabelText('School'), '1')
  return user
}

describe('StopProposalsSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getStopProposals).mockResolvedValue([proposal, existing])
  })

  it("lists a school's proposals with walks and warnings, and maps them", async () => {
    renderSection()
    await choose()
    expect(await screen.findByText('Proposed stop 1')).toBeInTheDocument()
    expect(api.getStopProposals).toHaveBeenCalledWith(1)
    expect(screen.getByText('Ana Lopez — walks 0.05 mi (limit 0.25 mi)')).toBeInTheDocument()
    expect(screen.getByText('⚠ Ben Ng would walk 0.30 mi (limit 0.25 mi)')).toBeInTheDocument()
    expect(screen.getByText('Existing stop')).toBeInTheDocument()
    // An existing stop can't be moved from here.
    expect(screen.getAllByRole('button', { name: 'Move on map' })).toHaveLength(1)
    const map = await findMap('Stop proposals map')
    expect(within(map).getByTitle('Proposed stop 1 (2)')).toBeInTheDocument()
    expect(within(map).getByTitle('Oak & 5th (1)')).toBeInTheDocument()
  })

  it('proposes stops and says who was left out', async () => {
    vi.mocked(api.generateStopProposals).mockResolvedValue({
      proposals: [proposal],
      students_considered: 2,
      already_have_stop: 3,
      no_home: 1,
      not_eligible: 4,
    })
    renderSection()
    const user = await choose()
    await user.click(screen.getByRole('button', { name: 'Propose stops' }))
    await waitFor(() => expect(api.generateStopProposals).toHaveBeenCalledWith(1))
    expect(
      await screen.findByText(
        /1 proposal\(s\) for 2 student\(s\)\. Left out: 3 already have a stop, 1 have no home on file, 4 aren't eligible\./,
      ),
    ).toBeInTheDocument()
  })

  it('approving refreshes Setup, rejecting does not', async () => {
    vi.mocked(api.approveStopProposal).mockResolvedValue({
      ...proposal,
      status: 'approved',
      stop_id: 11,
    })
    vi.mocked(api.rejectStopProposal).mockResolvedValue({ ...existing, status: 'rejected' })
    const onChanged = renderSection()
    const user = await choose()
    await screen.findByText('Proposed stop 1')

    const [approveNew] = screen.getAllByRole('button', { name: 'Approve' })
    await user.click(approveNew)
    await waitFor(() => expect(api.approveStopProposal).toHaveBeenCalledWith(4))
    expect(onChanged).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Reject' }))
    await waitFor(() => expect(api.rejectStopProposal).toHaveBeenCalledWith(5))
    expect(onChanged).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('Decided (2)')).toBeInTheDocument()
  })

  it('moves a proposal to where the map is clicked', async () => {
    vi.mocked(api.updateStopProposal).mockResolvedValue({ ...proposal, warnings: [] })
    renderSection()
    const user = await choose()
    await user.click(await screen.findByRole('button', { name: 'Move on map' }))
    expect(screen.getByText('Click the map to move Proposed stop 1.')).toBeInTheDocument()
    const map = await findMap('Stop proposals map')
    fireEvent.click(map, { clientX: 5, clientY: 5 })

    await waitFor(() => expect(api.updateStopProposal).toHaveBeenCalled())
    const [id, patch] = vi.mocked(api.updateStopProposal).mock.calls[0]
    expect(id).toBe(4)
    expect(Number.isFinite(patch.location_lat) && Number.isFinite(patch.location_lon)).toBe(true)
    expect(await screen.findByRole('button', { name: 'Move on map' })).toBeInTheDocument()
    expect(screen.queryByText(/would walk/)).not.toBeInTheDocument()
  })

  it('shows why an action failed', async () => {
    vi.mocked(api.approveStopProposal).mockRejectedValue(
      new ApiError(409, 'This proposal was already approved'),
    )
    renderSection()
    const user = await choose()
    await screen.findByText('Proposed stop 1')
    await user.click(screen.getAllByRole('button', { name: 'Approve' })[0])
    expect(await screen.findByRole('alert')).toHaveTextContent('already approved')
  })
})
