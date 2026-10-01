import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { AuthProvider } from '../auth/AuthContext'
import { AccountPage } from './AccountPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getCurrentUser: vi.fn(), changePassword: vi.fn(), getMfaStatus: vi.fn() }
})

function renderPage() {
  return render(
    <AuthProvider>
      <AccountPage />
    </AuthProvider>,
  )
}

async function fill(current: string, next: string, confirm: string) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Current password'), current)
  await user.type(screen.getByLabelText('New password'), next)
  await user.type(screen.getByLabelText('New password again'), confirm)
  await user.click(screen.getByRole('button', { name: 'Change password' }))
}

describe('AccountPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getMfaStatus).mockResolvedValue({
      allowed: false,
      required: false,
      enabled: false,
      recovery_codes_left: 0,
    })
    vi.mocked(api.getCurrentUser).mockResolvedValue({
      id: 4,
      email: 'pat@example.org',
      full_name: 'Pat Parent',
      role: 'parent',
      is_active: true,
      driver_id: null,
      school_id: null,
      student_id: null,
    })
  })

  it('changes the password and says other sessions ended', async () => {
    vi.mocked(api.changePassword).mockResolvedValue(undefined)
    renderPage()
    expect(await screen.findByText(/Signed in as Pat Parent/)).toBeInTheDocument()
    await fill('old-password', 'yellow-bus-7', 'yellow-bus-7')
    await waitFor(() =>
      expect(api.changePassword).toHaveBeenCalledWith('old-password', 'yellow-bus-7'),
    )
    expect(await screen.findByRole('status')).toHaveTextContent(
      "Password changed. You've been signed out everywhere else.",
    )
    expect(screen.getByLabelText('Current password')).toHaveValue('')
  })

  it('catches a mistyped confirmation before sending anything', async () => {
    renderPage()
    await fill('old-password', 'yellow-bus-7', 'yellow-bus-8')
    expect(await screen.findByRole('alert')).toHaveTextContent("The new passwords don't match.")
    expect(api.changePassword).not.toHaveBeenCalled()
  })

  it("shows the server's reason", async () => {
    vi.mocked(api.changePassword).mockRejectedValue(
      new ApiError(400, 'That password is too common; choose another'),
    )
    renderPage()
    await fill('old-password', 'password1', 'password1')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That password is too common; choose another',
    )
  })
})
