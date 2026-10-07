import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { Student } from '../api/types'
import { WithdrawControl } from './WithdrawControl'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, withdrawStudent: vi.fn(), reinstateStudent: vi.fn() }
})

const student = { id: 4, full_name: 'Ana Lopez' } as Student

describe('WithdrawControl', () => {
  beforeEach(() => vi.resetAllMocks())

  it('withdraws on a chosen date', async () => {
    vi.mocked(api.withdrawStudent).mockResolvedValue(student)
    const onChanged = vi.fn()
    render(<WithdrawControl student={student} onChanged={onChanged} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Withdraw' }))
    const date = screen.getByLabelText('Left the district on')
    await user.clear(date)
    await user.type(date, '2026-10-07')
    await user.click(screen.getByRole('button', { name: 'Confirm withdrawal' }))
    await waitFor(() => expect(api.withdrawStudent).toHaveBeenCalledWith(4, '2026-10-07'))
    expect(onChanged).toHaveBeenCalled()
  })

  it('shows when the data goes, and reinstates', async () => {
    vi.mocked(api.reinstateStudent).mockResolvedValue(student)
    render(
      <WithdrawControl
        student={{ ...student, withdrawn_on: '2026-10-07', delete_after: '2028-06-30' }}
        onChanged={vi.fn()}
      />,
    )
    expect(screen.getByText('Left 2026-10-07; data deleted after 2028-06-30')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Reinstate' }))
    await waitFor(() => expect(api.reinstateStudent).toHaveBeenCalledWith(4))
  })
})
