import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { SisSyncRun, SisSyncStatus } from '../api/types'
import { SisSyncPanel } from './SisSyncPanel'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getSisSyncStatus: vi.fn(), syncSisNow: vi.fn() }
})

const nightly: SisSyncRun = {
  id: 1,
  trigger: 'scheduled',
  status: 'ok',
  started_at: '2026-10-06T08:00:00Z',
  finished_at: '2026-10-06T08:00:05Z',
  counts: { created: 2, updated: 1, unchanged: 40 },
  problems: [],
  error: null,
}

const attention: SisSyncRun = {
  ...nightly,
  id: 2,
  trigger: 'manual',
  status: 'needs_attention',
  counts: { created: 0, updated: 0, unchanged: 43, needs_review: 1 },
  problems: [
    {
      line: 7,
      source_id: 's7',
      full_name: 'Hand Entered',
      action: 'needs_review',
      detail: 'Same name and school as hand-entered student 3',
      student_id: 3,
    },
  ],
}

function status(runs: SisSyncRun[], configured = true): SisSyncStatus {
  return { configured, sync_time: '03:00', runs }
}

describe('SisSyncPanel', () => {
  beforeEach(() => vi.resetAllMocks())

  it('explains it is not set up yet', async () => {
    vi.mocked(api.getSisSyncStatus).mockResolvedValue(status([], false))
    render(<SisSyncPanel />)
    expect(await screen.findByText(/Not set up/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument()
  })

  it('lists runs with their results', async () => {
    vi.mocked(api.getSisSyncStatus).mockResolvedValue(status([nightly]))
    render(<SisSyncPanel />)
    expect(await screen.findByText(/Every night at 03:00/)).toBeInTheDocument()
    const row = screen.getByText('Nightly').closest('tr') as HTMLElement
    expect(within(row).getByText('Done')).toBeInTheDocument()
    expect(within(row).getByText('2 new, 1 changed, 40 unchanged')).toBeInTheDocument()
  })

  it('syncs now and shows what waits for review', async () => {
    vi.mocked(api.getSisSyncStatus)
      .mockResolvedValueOnce(status([nightly]))
      .mockResolvedValueOnce(status([attention, nightly]))
    vi.mocked(api.syncSisNow).mockResolvedValue(attention)
    render(<SisSyncPanel />)
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Sync now' }))
    await waitFor(() => expect(api.syncSisNow).toHaveBeenCalled())
    const row = (await screen.findByText('Sync now', { selector: 'td' })).closest(
      'tr',
    ) as HTMLElement
    expect(within(row).getByText('Needs a look')).toBeInTheDocument()
    expect(within(row).getByText(/1 to review/)).toBeInTheDocument()
    expect(within(row).getByText('Hand Entered')).toBeInTheDocument()
    expect(within(row).getByText(/Same name and school/)).toBeInTheDocument()
  })

  it('shows why a sync could not start', async () => {
    vi.mocked(api.getSisSyncStatus).mockResolvedValue(status([]))
    vi.mocked(api.syncSisNow).mockRejectedValue(new ApiError(409, 'A sync is already running'))
    render(<SisSyncPanel />)
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Sync now' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A sync is already running')
  })
})
