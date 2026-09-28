import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { School, Student, StudentHome } from '../api/types'
import { StudentHomePanel } from './StudentHomePanel'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getStudentHome: vi.fn(),
    setStudentHome: vi.fn(),
    deleteStudentHome: vi.fn(),
  }
})

const school: School = { id: 1, name: 'Riverside', location_lat: 29.7, location_lon: -95.4 }
const student: Student = {
  id: 10,
  full_name: 'Jamie Student',
  school_id: 1,
  stop_id: null,
  default_ridership: 'rides',
}
const censusHome: StudentHome = {
  address: '123 Main St, Houston, TX 77002',
  location_lat: 29.736,
  location_lon: -95.4,
  source: 'census',
  matched_address: '123 MAIN ST, HOUSTON, TX, 77002',
  updated_at: '2026-09-28T12:00:00Z',
}

function renderPanel() {
  const onChanged = vi.fn().mockResolvedValue(undefined)
  render(<StudentHomePanel student={student} school={school} onChanged={onChanged} />)
  return onChanged
}

async function open() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Home' }))
  return user
}

describe('StudentHomePanel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('looks an address up with the Census and shows what it matched', async () => {
    vi.mocked(api.getStudentHome).mockRejectedValue(new ApiError(404, 'No home on file'))
    vi.mocked(api.setStudentHome).mockResolvedValue(censusHome)
    const onChanged = renderPanel()
    const user = await open()

    expect(await screen.findByText('No home location on file.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Home address'), '123 Main St, Houston, TX 77002')
    await user.click(screen.getByRole('button', { name: 'Look up with Census' }))

    await waitFor(() =>
      expect(api.setStudentHome).toHaveBeenCalledWith(10, {
        address: '123 Main St, Houston, TX 77002',
      }),
    )
    expect(
      await screen.findByText('Census match: 123 MAIN ST, HOUSTON, TX, 77002'),
    ).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
  })

  it("shows why the Census couldn't place it", async () => {
    vi.mocked(api.getStudentHome).mockRejectedValue(new ApiError(404, 'No home on file'))
    vi.mocked(api.setStudentHome).mockRejectedValue(
      new ApiError(422, "The Census geocoder couldn't find that address."),
    )
    renderPanel()
    const user = await open()
    await user.type(await screen.findByLabelText('Home address'), '1 Nowhere Rd')
    await user.click(screen.getByRole('button', { name: 'Look up with Census' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("couldn't find that address")
  })

  it('saves a spot placed on the map', async () => {
    vi.mocked(api.getStudentHome).mockResolvedValue(censusHome)
    vi.mocked(api.setStudentHome).mockResolvedValue({ ...censusHome, source: 'manual' })
    renderPanel()
    const user = await open()
    expect(await screen.findByDisplayValue('123 Main St, Houston, TX 77002')).toBeInTheDocument()
    const map = await screen.findByRole('region', { name: 'Home map for Jamie Student' })

    fireEvent.click(map, { clientX: 5, clientY: 5 })
    await user.click(await screen.findByRole('button', { name: 'Save the placed spot' }))

    await waitFor(() => expect(api.setStudentHome).toHaveBeenCalled())
    const [, body] = vi.mocked(api.setStudentHome).mock.calls[0]
    expect(body.address).toBe('123 Main St, Houston, TX 77002')
    expect(Number.isFinite(body.location_lat) && Number.isFinite(body.location_lon)).toBe(true)
    expect(await screen.findByText('Placed by hand on the map.')).toBeInTheDocument()
  })

  it('removes a home after confirming', async () => {
    vi.mocked(api.getStudentHome).mockResolvedValue(censusHome)
    vi.mocked(api.deleteStudentHome).mockResolvedValue(undefined)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onChanged = renderPanel()
    const user = await open()
    await user.click(await screen.findByRole('button', { name: 'Remove home' }))
    await waitFor(() => expect(api.deleteStudentHome).toHaveBeenCalledWith(10))
    expect(onChanged).toHaveBeenCalled()
    expect(await screen.findByText('No home location on file.')).toBeInTheDocument()
    confirm.mockRestore()
  })
})
