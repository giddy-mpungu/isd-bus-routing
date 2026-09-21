import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type { School, SisImportResult } from '../api/types'
import { SisImportSection } from './SisImportSection'

const onSchoolsChanged = vi.fn().mockResolvedValue(undefined)
function renderSection(schools: School[] = [school]) {
  return render(<SisImportSection schools={schools} onSchoolsChanged={onSchoolsChanged} />)
}

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    updateSchoolExternalId: vi.fn(),
    importSisStudents: vi.fn(),
  }
})

const school: School = {
  id: 1,
  name: 'Riverside Elementary',
  location_lat: 0,
  location_lon: 0,
  external_id: null,
}

function previewResult(overrides: Partial<SisImportResult> = {}): SisImportResult {
  return {
    dry_run: true,
    counts: {
      created: 2,
      updated: 1,
      unchanged: 5,
      linked: 0,
      needs_review: 1,
      removal_requested: 0,
      error: 1,
    },
    rows: [
      {
        line: 3,
        source_id: 's2',
        full_name: 'Ben Ng',
        action: 'needs_review',
        detail: 'Same name and school as hand-entered student 9',
        student_id: 9,
      },
      {
        line: 4,
        source_id: 's3',
        full_name: 'Cy Ohm',
        action: 'error',
        detail: 'None of this student’s organizations is mapped to a school here',
        student_id: null,
      },
    ],
    rows_truncated: false,
    ignored_non_student_rows: 3,
    ...overrides,
  }
}

const csvFile = new File(['sourcedId,givenName,familyName,orgSourcedIds\n'], 'users.csv', {
  type: 'text/csv',
})

describe('SisImportSection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    onSchoolsChanged.mockResolvedValue(undefined)
  })

  it('saves a school SIS ID and only enables Save once it changed', async () => {
    vi.mocked(api.updateSchoolExternalId).mockResolvedValue({ ...school, external_id: 'org-a' })
    const user = userEvent.setup()
    renderSection()
    const input = await screen.findByLabelText('SIS ID for Riverside Elementary')
    const save = screen.getByRole('button', { name: 'Save SIS ID for Riverside Elementary' })
    expect(save).toBeDisabled()

    await user.type(input, 'org-a')
    expect(save).toBeEnabled()
    await user.click(save)

    await waitFor(() => expect(api.updateSchoolExternalId).toHaveBeenCalledWith(1, 'org-a'))
    await waitFor(() => expect(onSchoolsChanged).toHaveBeenCalledTimes(1))
  })

  it('shows a conflict when the SIS ID is already taken', async () => {
    vi.mocked(api.updateSchoolExternalId).mockRejectedValue(
      new ApiError(409, 'Another school already has that SIS ID'),
    )
    const user = userEvent.setup()
    renderSection()
    await user.type(await screen.findByLabelText('SIS ID for Riverside Elementary'), 'org-a')
    await user.click(screen.getByRole('button', { name: 'Save SIS ID for Riverside Elementary' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('already has that SIS ID')
  })

  it('previews a file, shows counts and problem rows, then applies only after a preview', async () => {
    vi.mocked(api.importSisStudents)
      .mockResolvedValueOnce(previewResult())
      .mockResolvedValueOnce(previewResult({ dry_run: false }))
    const user = userEvent.setup()
    renderSection()
    await screen.findByLabelText('SIS ID for Riverside Elementary')

    const preview = screen.getByRole('button', { name: 'Preview import' })
    const apply = screen.getByRole('button', { name: 'Apply import' })
    expect(preview).toBeDisabled()
    expect(apply).toBeDisabled()

    await user.upload(screen.getByLabelText('users.csv'), csvFile)
    expect(apply).toBeDisabled() // a chosen file alone is not enough

    await user.click(preview)
    await waitFor(() => expect(api.importSisStudents).toHaveBeenCalledWith(csvFile, true, false))
    expect(await screen.findByText('Preview (nothing changed yet)')).toBeInTheDocument()
    expect(screen.getByText('2 to create')).toBeInTheDocument()
    expect(screen.getByText('1 need review')).toBeInTheDocument()
    expect(screen.getByText('3 non-student rows ignored')).toBeInTheDocument()
    expect(screen.getByText('Ben Ng')).toBeInTheDocument()
    expect(screen.getByText(/mapped to a school here/)).toBeInTheDocument()

    expect(apply).toBeEnabled()
    await user.click(apply)
    await waitFor(() =>
      expect(api.importSisStudents).toHaveBeenLastCalledWith(csvFile, false, false),
    )
    expect(await screen.findByText('Import applied')).toBeInTheDocument()
    expect(apply).toBeDisabled() // must preview again before applying again
  })

  it('requires a fresh preview when the link-by-name option changes', async () => {
    vi.mocked(api.importSisStudents).mockResolvedValue(previewResult())
    const user = userEvent.setup()
    renderSection()
    await screen.findByLabelText('SIS ID for Riverside Elementary')
    await user.upload(screen.getByLabelText('users.csv'), csvFile)
    await user.click(screen.getByRole('button', { name: 'Preview import' }))
    const apply = screen.getByRole('button', { name: 'Apply import' })
    await waitFor(() => expect(apply).toBeEnabled())

    await user.click(screen.getByLabelText(/Link to existing students/))
    expect(apply).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Preview import' }))
    await waitFor(() => expect(api.importSisStudents).toHaveBeenLastCalledWith(csvFile, true, true))
    await waitFor(() => expect(apply).toBeEnabled())
  })

  it('shows the API error for an unusable file', async () => {
    vi.mocked(api.importSisStudents).mockRejectedValue(
      new ApiError(400, 'Not a OneRoster users.csv: missing column(s) sourcedId'),
    )
    const user = userEvent.setup()
    renderSection()
    await screen.findByLabelText('SIS ID for Riverside Elementary')
    await user.upload(screen.getByLabelText('users.csv'), csvFile)
    await user.click(screen.getByRole('button', { name: 'Preview import' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Not a OneRoster users.csv')
    expect(screen.getByRole('button', { name: 'Apply import' })).toBeDisabled()
  })
})
