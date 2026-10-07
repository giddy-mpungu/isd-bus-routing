import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { Student } from '../api/types'
import { AccessLogPanel } from './AccessLogPanel'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getStudentAccessLog: vi.fn() }
})

const student = { id: 4, full_name: 'Ana Lopez' } as Student

describe('AccessLogPanel', () => {
  beforeEach(() => vi.resetAllMocks())

  it('lists who viewed the student, on request', async () => {
    vi.mocked(api.getStudentAccessLog).mockResolvedValue([
      {
        day: '2026-10-07',
        first_at: '2026-10-07T14:05:00Z',
        user_id: 2,
        user_name: 'Dana Dispatcher',
        user_role: 'dispatcher',
        what: 'list',
        what_label: 'the student list',
      },
    ])
    render(<AccessLogPanel student={student} />)
    expect(api.getStudentAccessLog).not.toHaveBeenCalled()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Who viewed' }))
    const panel = await screen.findByRole('region', { name: 'Who viewed Ana Lopez' })
    expect(within(panel).getByText('Dana Dispatcher')).toBeInTheDocument()
    expect(within(panel).getByText('dispatcher')).toBeInTheDocument()
    expect(within(panel).getByText('the student list')).toBeInTheDocument()
    expect(api.getStudentAccessLog).toHaveBeenCalledWith(4)
  })

  it('says when nobody has looked', async () => {
    vi.mocked(api.getStudentAccessLog).mockResolvedValue([])
    render(<AccessLogPanel student={student} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Who viewed' }))
    expect(await screen.findByText('Nobody has viewed this student yet.')).toBeInTheDocument()
  })
})
