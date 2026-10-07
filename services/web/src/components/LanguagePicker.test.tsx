import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { CurrentUser } from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { chooseLanguage } from '../i18n'
import { LoginPage } from '../pages/LoginPage'
import { axeViolations } from '../test/axe'
import { AppLayout } from '../layout/AppLayout'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getCurrentUser: vi.fn(),
    getAuthOptions: vi.fn(),
    setMyLanguage: vi.fn(),
  }
})

function person(role: CurrentUser['role'], preferred_language: string | null = null): CurrentUser {
  return {
    id: 1,
    email: 'a@example.org',
    full_name: 'Rosa Diaz',
    role,
    is_active: true,
    driver_id: null,
    school_id: null,
    student_id: null,
    preferred_language,
  }
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppLayout>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/family" element={<p>family page</p>} />
            <Route path="/schedule" element={<p>schedule page</p>} />
          </Routes>
        </AppLayout>
      </AuthProvider>
    </MemoryRouter>,
  )
}

// Every state these tests reach is checked against WCAG 2.1 A/AA.
afterEach(async () => {
  expect(await axeViolations()).toEqual([])
})

describe('choosing a language', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.getAuthOptions).mockResolvedValue({ email_enabled: true })
    vi.mocked(api.setMyLanguage).mockResolvedValue(person('parent', 'es'))
  })

  it('turns the sign-in page into Spanish, marked as awaiting review', async () => {
    vi.mocked(api.getCurrentUser).mockRejectedValue(new ApiError(401, 'Not signed in'))
    const user = userEvent.setup()
    renderAt('/login')
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Language'), 'es')

    expect(screen.getByRole('button', { name: 'Iniciar sesión' })).toBeInTheDocument()
    expect(screen.getByLabelText('Correo electrónico')).toBeInTheDocument()
    expect(screen.getByText('Traducción pendiente de revisión')).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('es')
    expect(document.title).toBe('Iniciar sesión · isd-bus-routing')
    // Nobody is signed in, so there's no account to save it to.
    expect(api.setMyLanguage).not.toHaveBeenCalled()
  })

  it("shows a family their account's language, and saves a new choice", async () => {
    vi.mocked(api.getCurrentUser).mockResolvedValue(person('parent', 'es'))
    const user = userEvent.setup()
    renderAt('/family')
    expect(await screen.findByRole('link', { name: 'Mi familia' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cerrar sesión' })).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Idioma'), 'en')
    expect(api.setMyLanguage).toHaveBeenCalledWith('en')
    expect(screen.getByRole('link', { name: 'My Family' })).toBeInTheDocument()
  })

  it('saves the language a family chose before signing in', async () => {
    chooseLanguage('es')
    vi.mocked(api.getCurrentUser).mockResolvedValue(person('parent'))
    renderAt('/family')
    await waitFor(() => expect(api.setMyLanguage).toHaveBeenCalledWith('es'))
    expect(await screen.findByRole('link', { name: 'Mi familia' })).toBeInTheDocument()
  })

  it('keeps the staff console in English, with no picker', async () => {
    chooseLanguage('es')
    vi.mocked(api.getCurrentUser).mockResolvedValue(person('dispatcher', 'es'))
    renderAt('/schedule')
    expect(await screen.findByRole('button', { name: 'Log out' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Language')).not.toBeInTheDocument()
    expect(document.documentElement.lang).toBe('en')
    expect(api.setMyLanguage).not.toHaveBeenCalled()
  })
})
