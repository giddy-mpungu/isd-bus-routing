import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { EtaEmailSetting } from './EtaEmailSetting'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, getNotificationSettings: vi.fn(), updateNotificationSettings: vi.fn() }
})

const LABEL = "Email me when my child's bus time changes by 10 minutes or more"

describe('EtaEmailSetting', () => {
  beforeEach(() => vi.resetAllMocks())

  it('is on by default and turns off', async () => {
    vi.mocked(api.getNotificationSettings).mockResolvedValue({ eta_emails: true })
    vi.mocked(api.updateNotificationSettings).mockResolvedValue({ eta_emails: false })
    render(<EtaEmailSetting />)
    const box = await screen.findByLabelText(LABEL)
    expect(box).toBeChecked()
    await userEvent.setup().click(box)
    await waitFor(() =>
      expect(api.updateNotificationSettings).toHaveBeenCalledWith({ eta_emails: false }),
    )
    expect(box).not.toBeChecked()
  })

  it("isn't shown to accounts it doesn't apply to", async () => {
    vi.mocked(api.getNotificationSettings).mockRejectedValue(new ApiError(403, 'Forbidden'))
    const { container } = render(<EtaEmailSetting />)
    await waitFor(() => expect(api.getNotificationSettings).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
