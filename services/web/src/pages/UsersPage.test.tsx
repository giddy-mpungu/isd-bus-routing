import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { CurrentUser, Driver, School, Student, User } from '../api/types'
import { AuthProvider } from '../auth/AuthContext'
import { UsersPage } from './UsersPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getCurrentUser: vi.fn(),
    getUsers: vi.fn(),
    createUser: vi.fn(),
    updateUser: vi.fn(),
    getDrivers: vi.fn(),
    getSchools: vi.fn(),
    getStudents: vi.fn(),
  }
})

const me: CurrentUser = {
  id: 1,
  email: 'admin@example.org',
  full_name: 'Admin Admin',
  role: 'transportation_admin',
  is_active: true,
  driver_id: null,
  school_id: null,
  student_id: null,
}

const dispatcherUser: User = {
  id: 2,
  email: 'disp@example.org',
  full_name: 'Dana Dispatcher',
  role: 'dispatcher',
  is_active: true,
  driver_id: null,
  school_id: null,
  student_id: null,
  created_at: '2026-09-01T00:00:00Z',
}

const driverUser: User = {
  id: 3,
  email: 'drv@example.org',
  full_name: 'Jordan Login',
  role: 'driver',
  is_active: true,
  driver_id: 5,
  school_id: null,
  student_id: null,
  created_at: '2026-09-01T00:00:00Z',
}

const driverRecord: Driver = {
  id: 5,
  full_name: 'Jordan Driver',
  max_continuous_minutes: null,
  license_class: 'cdl_b',
  is_active: true,
  qualifications: [],
}

const school: School = { id: 7, name: 'Riverside Elementary', location_lat: 0, location_lon: 0 }

function mockLoad(users: User[] = [dispatcherUser, driverUser]) {
  vi.mocked(api.getCurrentUser).mockResolvedValue(me)
  vi.mocked(api.getUsers).mockResolvedValue([
    { ...me, created_at: '2026-01-01T00:00:00Z' },
    ...users,
  ])
  vi.mocked(api.getDrivers).mockResolvedValue([driverRecord])
  vi.mocked(api.getSchools).mockResolvedValue([school])
  vi.mocked(api.getStudents).mockResolvedValue([] as Student[])
}

function renderPage() {
  return render(
    <AuthProvider>
      <UsersPage />
    </AuthProvider>,
  )
}

describe('UsersPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockLoad()
  })

  it('lists users with their role, status and linked record name', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('drv@example.org')).toBeInTheDocument())

    const row = screen.getByText('drv@example.org').closest('tr') as HTMLElement
    expect(within(row).getByText('driver')).toBeInTheDocument()
    expect(within(row).getByText('Jordan Driver')).toBeInTheDocument()
    expect(within(row).getByText('Active')).toBeInTheDocument()
  })

  it('creates a user with a driver role and linked driver record', async () => {
    vi.mocked(api.createUser).mockResolvedValue(driverUser)
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByText('drv@example.org')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Email'), 'new@example.org')
    await user.type(screen.getByLabelText('Password'), 'password123')
    await user.type(screen.getByLabelText('Full name'), 'New Driver')
    await user.selectOptions(screen.getByLabelText('Role'), 'driver')
    await user.selectOptions(screen.getByLabelText('Linked driver record'), '5')
    await user.click(screen.getByRole('button', { name: 'Add user' }))

    await waitFor(() =>
      expect(api.createUser).toHaveBeenCalledWith({
        email: 'new@example.org',
        password: 'password123',
        full_name: 'New Driver',
        role: 'driver',
        driver_id: 5,
        school_id: undefined,
        student_id: undefined,
      }),
    )
  })

  it('shows the API error when creating a user fails', async () => {
    vi.mocked(api.createUser).mockRejectedValue(new ApiError(409, 'Email already registered'))
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByText('drv@example.org')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Email'), 'dup@example.org')
    await user.type(screen.getByLabelText('Password'), 'password123')
    await user.type(screen.getByLabelText('Full name'), 'Dup')
    await user.click(screen.getByRole('button', { name: 'Add user' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Email already registered')
  })

  it('edits a role and its linked record', async () => {
    vi.mocked(api.updateUser).mockResolvedValue({ ...dispatcherUser, role: 'school_admin' })
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByText('disp@example.org')).toBeInTheDocument())

    const row = screen.getByText('disp@example.org').closest('tr') as HTMLElement
    await user.click(within(row).getByRole('button', { name: 'Edit' }))
    const editForm = screen.getByRole('button', { name: 'Save' }).closest('form') as HTMLElement
    await user.selectOptions(within(editForm).getByLabelText('Role'), 'school_admin')
    await user.selectOptions(within(editForm).getByLabelText('School'), '7')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateUser).toHaveBeenCalledWith(2, {
        role: 'school_admin',
        driver_id: undefined,
        school_id: 7,
        student_id: undefined,
      }),
    )
  })

  it('deactivates and reactivates another user', async () => {
    vi.mocked(api.updateUser).mockResolvedValue({ ...dispatcherUser, is_active: false })
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByText('disp@example.org')).toBeInTheDocument())

    const row = screen.getByText('disp@example.org').closest('tr') as HTMLElement
    await user.click(within(row).getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith(2, { is_active: false }))
  })

  it('disables deactivating your own account', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('admin@example.org')).toBeInTheDocument())

    const row = screen.getByText('admin@example.org').closest('tr') as HTMLElement
    expect(within(row).getByRole('button', { name: 'Deactivate' })).toBeDisabled()
  })

  it('shows a row error when the update fails', async () => {
    vi.mocked(api.updateUser).mockRejectedValue(
      new ApiError(400, 'You cannot deactivate your own account'),
    )
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByText('disp@example.org')).toBeInTheDocument())

    const row = screen.getByText('disp@example.org').closest('tr') as HTMLElement
    await user.click(within(row).getByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'You cannot deactivate your own account',
    )
  })

  it('shows a load error', async () => {
    vi.mocked(api.getUsers).mockRejectedValue(new ApiError(403, 'Forbidden'))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden')
  })
})
