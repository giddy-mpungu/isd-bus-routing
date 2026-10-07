import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { ForgotPasswordPage } from './ForgotPasswordPage'
import { axeViolations } from '../test/axe'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, forgotPassword: vi.fn() }
})

async function ask(email: string) {
  render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>,
  )
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), email)
  await user.click(screen.getByRole('button', { name: 'Email me a link' }))
}

// Every state these tests reach is checked against WCAG 2.1 A/AA.
afterEach(async () => {
  expect(await axeViolations()).toEqual([])
})

describe('ForgotPasswordPage', () => {
  beforeEach(() => vi.resetAllMocks())

  it("shows the server's neutral reply", async () => {
    vi.mocked(api.forgotPassword).mockResolvedValue(
      'If that email has an account, a link to reset its password is on its way.',
    )
    await ask('pat@example.org')
    await waitFor(() => expect(api.forgotPassword).toHaveBeenCalledWith('pat@example.org'))
    expect(await screen.findByRole('status')).toHaveTextContent(
      'If that email has an account, a link to reset its password is on its way.',
    )
    expect(screen.getByRole('link', { name: 'Back to sign in' })).toHaveAttribute('href', '/login')
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
  })

  it('says when email is not set up', async () => {
    vi.mocked(api.forgotPassword).mockRejectedValue(
      new ApiError(
        503,
        "Email isn't set up here. Ask your transportation office for a reset link.",
      ),
    )
    await ask('pat@example.org')
    expect(await screen.findByRole('alert')).toHaveTextContent("Email isn't set up here.")
  })
})
