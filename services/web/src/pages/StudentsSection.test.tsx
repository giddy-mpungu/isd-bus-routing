import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { Qualification, School, Stop, Student, User } from '../api/types'
import { StudentsSection } from './StudentsSection'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    createStudent: vi.fn(),
    updateStudent: vi.fn(),
    getGuardians: vi.fn(),
    getUsers: vi.fn(),
    linkGuardian: vi.fn(),
    unlinkGuardian: vi.fn(),
  }
})

const schools: School[] = [
  { id: 1, name: 'Riverside Elementary', location_lat: 29.7, location_lon: -95.4 },
  { id: 2, name: 'North Middle', location_lat: 29.8, location_lon: -95.5 },
]
const stops: Stop[] = [
  { id: 5, label: 'Oak & 5th', location_lat: 29.71, location_lon: -95.41 },
  { id: 6, label: 'Elm & 2nd', location_lat: 29.72, location_lon: -95.42 },
]
const jamie: Student = {
  id: 10,
  full_name: 'Jamie Student',
  school_id: 1,
  stop_id: 5,
  default_ridership: 'rides',
  external_id: null,
}
const parentUser = (id: number, name: string): User => ({
  id,
  email: `${name.toLowerCase()}@example.org`,
  full_name: name,
  role: 'parent',
  is_active: true,
  driver_id: null,
  school_id: null,
  student_id: null,
  created_at: '2026-09-01T00:00:00Z',
})

function renderSection(props: Partial<Parameters<typeof StudentsSection>[0]> = {}) {
  const onChanged = vi.fn().mockResolvedValue(undefined)
  render(
    <StudentsSection
      students={[jamie]}
      schools={schools}
      stops={stops}
      canEdit
      onChanged={onChanged}
      {...props}
    />,
  )
  return onChanged
}

describe('StudentsSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('reassigns a student to another school and stop', async () => {
    vi.mocked(api.updateStudent).mockResolvedValue({ ...jamie, school_id: 2, stop_id: 6 })
    const onChanged = renderSection()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Edit Jamie Student' }))
    await user.selectOptions(screen.getByLabelText("Student's school"), 'North Middle')
    // By value: user-event matches option text against innerHTML, where "&" is "&amp;".
    await user.selectOptions(screen.getByLabelText("Student's stop"), '6')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateStudent).toHaveBeenCalledWith(10, {
        full_name: 'Jamie Student',
        school_id: 2,
        grade: null,
        stop_id: 6,
        default_ridership: 'rides',
        needs_specialized_transport: false,
        hazardous_route: false,
        accommodation_codes: [],
      }),
    )
    expect(onChanged).toHaveBeenCalled()
  })

  it('clears the stop when set back to not yet assigned', async () => {
    vi.mocked(api.updateStudent).mockResolvedValue({ ...jamie, stop_id: null })
    renderSection()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit Jamie Student' }))
    await user.selectOptions(screen.getByLabelText("Student's stop"), 'Not yet assigned')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateStudent).toHaveBeenCalledWith(
        10,
        expect.objectContaining({ stop_id: null }),
      ),
    )
  })

  it('locks name and school for a student from the SIS and does not send them', async () => {
    vi.mocked(api.updateStudent).mockResolvedValue(jamie)
    renderSection({ students: [{ ...jamie, external_id: 'sis-1' }] })
    expect(screen.getByText('From SIS')).toBeInTheDocument()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Edit Jamie Student' }))
    expect(screen.getByLabelText("Student's name")).toBeDisabled()
    expect(screen.getByLabelText("Student's school")).toBeDisabled()
    expect(screen.getByText(/come from the SIS roster/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      // No name, school or grade: the SIS owns those.
      expect(api.updateStudent).toHaveBeenCalledWith(10, {
        stop_id: 5,
        default_ridership: 'rides',
        needs_specialized_transport: false,
        hazardous_route: false,
        accommodation_codes: [],
      }),
    )
  })

  it('shows the server error when saving fails', async () => {
    vi.mocked(api.updateStudent).mockRejectedValue(new ApiError(400, 'Unknown school_id'))
    renderSection()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit Jamie Student' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Unknown school_id')
  })

  it('offers no edit or guardian controls without edit rights', () => {
    renderSection({ canEdit: false })
    expect(screen.queryByRole('button', { name: 'Edit Jamie Student' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Guardians' })).not.toBeInTheDocument()
  })

  it('lists, links and unlinks guardians', async () => {
    const pat = parentUser(30, 'Pat')
    const sam = parentUser(31, 'Sam')
    vi.mocked(api.getUsers).mockResolvedValue([pat, sam])
    vi.mocked(api.getGuardians)
      .mockResolvedValueOnce([{ user_id: 30, full_name: 'Pat', email: pat.email }])
      .mockResolvedValueOnce([
        { user_id: 30, full_name: 'Pat', email: pat.email },
        { user_id: 31, full_name: 'Sam', email: sam.email },
      ])
      .mockResolvedValueOnce([{ user_id: 31, full_name: 'Sam', email: sam.email }])
    vi.mocked(api.linkGuardian).mockResolvedValue(undefined)
    vi.mocked(api.unlinkGuardian).mockResolvedValue(undefined)
    renderSection()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Guardians' }))
    expect(await screen.findByText(/Pat \(pat@example.org\)/)).toBeInTheDocument()
    // An already-linked parent isn't offered again.
    const choice = screen.getByLabelText('Link a parent account')
    expect(within(choice).queryByText(/Pat/)).not.toBeInTheDocument()

    await user.selectOptions(choice, 'Sam (sam@example.org)')
    await user.click(screen.getByRole('button', { name: 'Link guardian' }))
    await waitFor(() => expect(api.linkGuardian).toHaveBeenCalledWith(10, 31))
    expect(await screen.findByText(/Sam \(sam@example.org\)/)).toBeInTheDocument()

    const patRow = screen.getByText(/Pat \(pat@example.org\)/).closest('li') as HTMLElement
    await user.click(within(patRow).getByRole('button', { name: 'Unlink' }))
    await waitFor(() => expect(api.unlinkGuardian).toHaveBeenCalledWith(10, 30))
    // Pat leaves the linked list and is offered in the dropdown again.
    const linkedGuardians = () => {
      const panel = screen
        .getByRole('button', { name: 'Hide guardians' })
        .closest('.guardians-panel') as HTMLElement
      return within(panel)
        .queryAllByRole('listitem')
        .map((li) => li.textContent)
    }
    await waitFor(() => expect(linkedGuardians()).toEqual([expect.stringContaining('Sam')]))
    expect(
      within(screen.getByLabelText('Link a parent account')).getByText(/Pat/),
    ).toBeInTheDocument()
  })

  it('says when no parent account can see the student yet', async () => {
    vi.mocked(api.getUsers).mockResolvedValue([])
    vi.mocked(api.getGuardians).mockResolvedValue([])
    renderSection()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Guardians' }))
    expect(await screen.findByText(/No parent account can see Jamie Student/)).toBeInTheDocument()
    expect(screen.getByText(/Create one on the Users page/)).toBeInTheDocument()
  })

  it('shows grade, eligibility with its reason, and needs on the bus', () => {
    renderSection({
      students: [
        {
          ...jamie,
          grade: '3',
          accommodations: [lift],
          eligibility: {
            eligible: true,
            reason: '2.50 mi from school (at least 2 mi)',
            miles_from_school: 2.5,
            band: 'elementary',
          },
        },
      ],
    })
    const row = screen.getByText(/Jamie Student/).closest('li') as HTMLElement
    expect(row).toHaveTextContent('Grade 3')
    expect(within(row).getByText('Eligible')).toBeInTheDocument()
    expect(within(row).getByText('2.50 mi from school (at least 2 mi)')).toBeInTheDocument()
    expect(within(row).getByText('Wheelchair lift')).toBeInTheDocument()
  })

  it('edits grade, specialized transportation, hazardous route and accommodations', async () => {
    vi.mocked(api.updateStudent).mockResolvedValue(jamie)
    const onChanged = renderSection({ qualifications: [lift, licence] })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit Jamie Student' }))

    // Only vehicle capabilities are offered as needs, not licence tags.
    expect(screen.queryByLabelText('CDL B')).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText("Student's grade"), 'K')
    await user.click(screen.getByLabelText('Receives specialized transportation'))
    await user.click(screen.getByLabelText('Hazardous walking route (eligible at any distance)'))
    await user.click(screen.getByLabelText('Wheelchair lift'))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateStudent).toHaveBeenCalledWith(
        10,
        expect.objectContaining({
          grade: 'K',
          needs_specialized_transport: true,
          hazardous_route: true,
          accommodation_codes: ['wheelchair_lift'],
        }),
      ),
    )
    expect(onChanged).toHaveBeenCalled()
  })

  it("locks a SIS student's grade", async () => {
    renderSection({ students: [{ ...jamie, external_id: 'stu-1', grade: '4' }] })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit Jamie Student' }))
    expect(screen.getByLabelText("Student's grade")).toBeDisabled()
  })

  it('sends the grade when adding a student', async () => {
    vi.mocked(api.createStudent).mockResolvedValue(jamie)
    renderSection()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Student name'), 'Sam New')
    await user.selectOptions(screen.getByLabelText('School'), '1')
    await user.selectOptions(screen.getByLabelText('Grade (optional)'), 'PK')
    await user.click(screen.getByRole('button', { name: 'Add student' }))
    await waitFor(() =>
      expect(api.createStudent).toHaveBeenCalledWith(expect.objectContaining({ grade: 'PK' })),
    )
  })
})

const lift: Qualification = {
  id: 1,
  code: 'wheelchair_lift',
  kind: 'vehicle_capability',
  description: 'Wheelchair lift',
  is_active: true,
}
const licence: Qualification = {
  id: 2,
  code: 'cdl_b',
  kind: 'license',
  description: 'CDL B',
  is_active: true,
}
