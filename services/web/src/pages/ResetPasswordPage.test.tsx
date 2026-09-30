import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { ResetPasswordPage } from './ResetPasswordPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, resetPassword: vi.fn() }
})

function openLink(hash: string) {
  window.history.replaceState(null, '', `/reset-password${hash}`)
  return render(
    <MemoryRouter>
      <ResetPasswordPage />
    </MemoryRouter>,
  )
}

async function submit(next: string, confirm = next) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('New password'), next)
  await user.type(screen.getByLabelText('New password again'), confirm)
  await user.click(screen.getByRole('button', { name: 'Set password' }))
}

describe('ResetPasswordPage', () => {
  beforeEach(() => vi.resetAllMocks())
  afterEach(() => window.history.replaceState(null, '', '/'))

  it('takes the token out of the address bar and sets the password', async () => {
    vi.mocked(api.resetPassword).mockResolvedValue(undefined)
    openLink('#token=abc123')
    expect(window.location.hash).toBe('')
    await submit('yellow-bus-7')
    await waitFor(() => expect(api.resetPassword).toHaveBeenCalledWith('abc123', 'yellow-bus-7'))
    expect(await screen.findByRole('status')).toHaveTextContent('Your password is set.')
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
  })

  it('explains an expired or used link', async () => {
    vi.mocked(api.resetPassword).mockRejectedValue(
      new ApiError(400, 'This reset link has expired or was already used. Ask for a new one.'),
    )
    openLink('#token=abc123')
    await submit('yellow-bus-7')
    expect(await screen.findByRole('alert')).toHaveTextContent('expired or was already used')
  })

  it('catches mismatched passwords', async () => {
    openLink('#token=abc123')
    await submit('yellow-bus-7', 'yellow-bus-8')
    expect(await screen.findByRole('alert')).toHaveTextContent("The passwords don't match.")
    expect(api.resetPassword).not.toHaveBeenCalled()
  })

  it('says so when the link has no token', () => {
    openLink('')
    expect(screen.getByRole('alert')).toHaveTextContent('This link is incomplete.')
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument()
  })
})
