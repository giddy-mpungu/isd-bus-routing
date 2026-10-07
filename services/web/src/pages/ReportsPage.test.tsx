import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Report } from '../api/types'
import { ReportsPage } from './ReportsPage'
import { axeViolations } from '../test/axe'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getReport: vi.fn() }
})

const report: Report = {
  name: 'assignments',
  title: 'Assignments and on-time performance',
  start: '2026-10-01',
  end: '2026-10-05',
  columns: ['Date', 'School', 'Minutes late', 'Started'],
  rows: [
    ['2026-10-05', 'Riverside', 3, '07:02'],
    ['2026-10-05', 'Northside', null, null],
  ],
  total_rows: 2,
  summary: { Assignments: 2, 'On-time %': 50, 'Average minutes late (late runs)': null },
}

async function showReport(name = 'assignments') {
  const user = userEvent.setup()
  await user.selectOptions(screen.getByLabelText('Report'), name)
  await user.clear(screen.getByLabelText('From'))
  await user.type(screen.getByLabelText('From'), '2026-10-01')
  await user.clear(screen.getByLabelText('To'))
  await user.type(screen.getByLabelText('To'), '2026-10-05')
  await user.click(screen.getByRole('button', { name: 'Show report' }))
  return user
}

// Every state these tests reach is checked against WCAG 2.1 A/AA.
afterEach(async () => {
  expect(await axeViolations()).toEqual([])
})

describe('ReportsPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('shows the summary, the rows and a CSV download for the range', async () => {
    vi.mocked(api.getReport).mockResolvedValue(report)
    render(<ReportsPage />)
    await showReport()

    await waitFor(() =>
      expect(api.getReport).toHaveBeenCalledWith('assignments', '2026-10-01', '2026-10-05'),
    )
    expect(
      await screen.findByRole('heading', {
        name: 'Assignments and on-time performance: 2026-10-01 to 2026-10-05',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('On-time %').nextSibling).toHaveTextContent('50')
    expect(screen.getByText('Average minutes late (late runs)').nextSibling).toHaveTextContent('—')

    const table = screen.getByRole('table')
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((th) => th.textContent),
    ).toEqual(report.columns)
    expect(within(table).getAllByRole('row')).toHaveLength(3)

    const link = screen.getByRole('link', { name: 'Download CSV (2 rows)' })
    expect(link.getAttribute('href')).toMatch(
      /\/reports\/assignments\/csv\?start=2026-10-01&end=2026-10-05$/,
    )
  })

  it('says when the preview is only part of the report', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ ...report, total_rows: 1200 })
    render(<ReportsPage />)
    await showReport()
    expect(
      await screen.findByText('Showing the first 2 of 1200 rows. The CSV has them all.'),
    ).toBeInTheDocument()
  })

  it('says when a range is empty', async () => {
    vi.mocked(api.getReport).mockResolvedValue({ ...report, rows: [], total_rows: 0 })
    render(<ReportsPage />)
    await showReport()
    expect(await screen.findByText('Nothing in this range.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows why the server refused the range', async () => {
    vi.mocked(api.getReport).mockRejectedValue(
      new ApiError(400, 'This report covers at most 7 days at a time'),
    )
    render(<ReportsPage />)
    await showReport('positions')
    expect(await screen.findByRole('alert')).toHaveTextContent('at most 7 days')
    expect(screen.getByText('Up to 7 days at a time.')).toBeInTheDocument()
  })

  it('hides a shown report once the controls change, so its CSV link stays honest', async () => {
    vi.mocked(api.getReport).mockResolvedValue(report)
    render(<ReportsPage />)
    const user = await showReport()
    expect(await screen.findByRole('link', { name: /Download CSV/ })).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Report'), 'field-trips')
    expect(screen.queryByRole('link', { name: /Download CSV/ })).not.toBeInTheDocument()
  })
})
