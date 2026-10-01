import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { MfaStatus } from '../api/types'
import { TwoStepSection } from './TwoStepSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getMfaStatus: vi.fn(),
    startMfaSetup: vi.fn(),
    confirmMfa: vi.fn(),
    replaceRecoveryCodes: vi.fn(),
    disableMfa: vi.fn(),
  }
})

const off: MfaStatus = { allowed: true, required: false, enabled: false, recovery_codes_left: 0 }
const on: MfaStatus = { allowed: true, required: false, enabled: true, recovery_codes_left: 7 }

describe('TwoStepSection', () => {
  beforeEach(() => vi.resetAllMocks())

  it('turns it on from the Account page', async () => {
    vi.mocked(api.getMfaStatus).mockResolvedValueOnce(off).mockResolvedValueOnce(on)
    vi.mocked(api.startMfaSetup).mockResolvedValue({
      secret: 'JBSWY3DPEHPK3PXP',
      otpauth_uri: 'otpauth://totp/x?secret=JBSWY3DPEHPK3PXP',
    })
    vi.mocked(api.confirmMfa).mockResolvedValue({ recovery_codes: ['AAAAA-BBBBB'] })
    render(<TwoStepSection />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Turn on two-step sign-in' }))
    await user.type(await screen.findByLabelText('6-digit code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Turn on two-step sign-in' }))
    await user.click(await screen.findByRole('button', { name: "I've saved them" }))
    expect(await screen.findByText(/You have 7 recovery codes left/)).toBeInTheDocument()
  })

  it('makes new recovery codes and turns it off with the password', async () => {
    vi.mocked(api.getMfaStatus).mockResolvedValueOnce(on).mockResolvedValue(off)
    vi.mocked(api.replaceRecoveryCodes).mockResolvedValue(['EEEEE-FFFFF'])
    vi.mocked(api.disableMfa).mockResolvedValue(undefined)
    render(<TwoStepSection />)
    const user = userEvent.setup()
    await user.type(
      await screen.findByLabelText('Code from your app, to make new recovery codes'),
      '111111',
    )
    await user.click(screen.getByRole('button', { name: 'Make new recovery codes' }))
    expect(await screen.findByRole('region', { name: 'Recovery codes' })).toHaveTextContent(
      'EEEEE-FFFFF',
    )
    expect(api.replaceRecoveryCodes).toHaveBeenCalledWith('111111')
  })

  it('turns it off with the password', async () => {
    vi.mocked(api.getMfaStatus).mockResolvedValueOnce(on).mockResolvedValue(off)
    vi.mocked(api.disableMfa).mockResolvedValue(undefined)
    render(<TwoStepSection />)
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Password, to turn it off'), 'my-password')
    await user.click(screen.getByRole('button', { name: 'Turn off two-step sign-in' }))
    await waitFor(() => expect(api.disableMfa).toHaveBeenCalledWith('my-password'))
    expect(await screen.findByText(/^Off\./)).toBeInTheDocument()
  })

  it("keeps it on for roles that need it, and isn't shown to drivers", async () => {
    vi.mocked(api.getMfaStatus).mockResolvedValue({ ...on, required: true })
    const { unmount } = render(<TwoStepSection />)
    expect(
      await screen.findByText('Your role needs two-step sign-in, so it stays on.'),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Password, to turn it off')).not.toBeInTheDocument()
    unmount()

    vi.mocked(api.getMfaStatus).mockResolvedValue({ ...off, allowed: false })
    const { container } = render(<TwoStepSection />)
    await waitFor(() => expect(api.getMfaStatus).toHaveBeenCalledTimes(2))
    expect(container).toBeEmptyDOMElement()
  })

  it('shows why a code was refused', async () => {
    vi.mocked(api.getMfaStatus).mockResolvedValue(on)
    vi.mocked(api.replaceRecoveryCodes).mockRejectedValue(
      new ApiError(
        400,
        "That code didn't work. Enter the newest code from your authenticator app.",
      ),
    )
    render(<TwoStepSection />)
    const user = userEvent.setup()
    await user.type(
      await screen.findByLabelText('Code from your app, to make new recovery codes'),
      '000000',
    )
    await user.click(screen.getByRole('button', { name: 'Make new recovery codes' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("That code didn't work.")
  })
})
