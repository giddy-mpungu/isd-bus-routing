import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { EmailPreferencesPage } from './EmailPreferencesPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, optOutOfEtaEmails: vi.fn() }
})

function openLink(hash: string) {
  window.history.replaceState(null, '', `/email-preferences${hash}`)
  return render(
    <MemoryRouter>
      <EmailPreferencesPage />
    </MemoryRouter>,
  )
}

describe('EmailPreferencesPage', () => {
  beforeEach(() => vi.resetAllMocks())
  afterEach(() => window.history.replaceState(null, '', '/'))

  it('waits for a click, so a link scanner opening it changes nothing', async () => {
    vi.mocked(api.optOutOfEtaEmails).mockResolvedValue(undefined)
    openLink('#token=abc.def')
    expect(window.location.hash).toBe('')
    expect(api.optOutOfEtaEmails).not.toHaveBeenCalled()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Stop bus time emails' }))
    await waitFor(() => expect(api.optOutOfEtaEmails).toHaveBeenCalledWith('abc.def'))
    expect(await screen.findByRole('status')).toHaveTextContent(
      "you won't get bus time emails any more",
    )
  })

  it('explains an expired link', async () => {
    vi.mocked(api.optOutOfEtaEmails).mockRejectedValue(
      new ApiError(
        400,
        'This link has expired. Turn bus time emails off on the Family page instead.',
      ),
    )
    openLink('#token=old')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Stop bus time emails' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This link has expired.')
  })

  it('says so when the link has no token', () => {
    openLink('')
    expect(screen.getByRole('alert')).toHaveTextContent('This link is incomplete.')
  })
})
