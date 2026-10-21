import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { axeViolations } from '../test/axe'
import { AbsenceImportSection } from './AbsenceImportSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, importAbsences: vi.fn() }
})

const rows = [
  {
    line: 2,
    driver: 'Jordan Rivera',
    date: '2026-10-21',
    outcome: 'created' as const,
    message: null,
  },
  {
    line: 3,
    driver: 'Nobody Here',
    date: '2026-10-21',
    outcome: 'error' as const,
    message: 'No driver by that name',
  },
]

describe('AbsenceImportSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  afterEach(async () => {
    expect(await axeViolations()).toEqual([])
  })

  it('previews an HR export, then imports what can be', async () => {
    vi.mocked(api.importAbsences)
      .mockResolvedValueOnce({ applied: false, rows })
      .mockResolvedValueOnce({ applied: true, rows })
    const user = userEvent.setup()
    render(<AbsenceImportSection />)
    const text = 'employee_id,driver,date\nE100,,2026-10-21\n,Nobody Here,2026-10-21\n'
    await user.type(
      screen.getByLabelText('Or paste the HR export'),
      text.replaceAll('\n', '{Enter}'),
    )
    await user.click(screen.getByRole('button', { name: 'Preview' }))

    expect(await screen.findByText('Preview: nothing saved yet')).toBeInTheDocument()
    expect(screen.getByText('error: No driver by that name')).toBeInTheDocument()
    expect(api.importAbsences).toHaveBeenLastCalledWith(expect.stringContaining('E100'), false)
    await user.click(screen.getByRole('button', { name: 'Import 1 absence' }))
    await waitFor(() =>
      expect(api.importAbsences).toHaveBeenLastCalledWith(expect.any(String), true),
    )
    expect(await screen.findByText('Imported')).toBeInTheDocument()
  })
})
