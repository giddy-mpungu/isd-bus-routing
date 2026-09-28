import { useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  Guardian,
  Qualification,
  RidershipDefault,
  School,
  Stop,
  Student,
  User,
} from '../api/types'
import { Badge } from '../components/Badge'
import { StudentHomePanel } from './StudentHomePanel'

const GRADES = ['PK', 'K', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']

function gradeLabel(grade: string | null | undefined): string {
  if (grade == null) return 'grade not set'
  if (grade === 'PK') return 'Pre-K'
  if (grade === 'K') return 'Kindergarten'
  return `Grade ${grade}`
}

// Spec section 21 "reassign students" and section 18: which parent accounts
// may see a child is decided here, by a transportation administrator.
function GuardiansPanel({ student }: { student: Student }) {
  const [guardians, setGuardians] = useState<Guardian[] | null>(null)
  const [parents, setParents] = useState<User[]>([])
  const [choice, setChoice] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setIsBusy] = useState(false)
  const [open, setOpen] = useState(false)

  async function load() {
    const [linked, users] = await Promise.all([api.getGuardians(student.id), api.getUsers()])
    setGuardians(linked)
    setParents(users.filter((u) => u.role === 'parent' && u.is_active))
  }

  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && guardians === null) {
      setError(null)
      try {
        await load()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Failed to load guardians.')
      }
    }
  }

  async function run(action: () => Promise<void>, failure: string) {
    setError(null)
    setIsBusy(true)
    try {
      await action()
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : failure)
    } finally {
      setIsBusy(false)
    }
  }

  const linkedIds = new Set((guardians ?? []).map((g) => g.user_id))
  const linkable = parents.filter((p) => !linkedIds.has(p.id))

  return (
    <div className="guardians-panel">
      <button type="button" onClick={() => void toggle()} aria-expanded={open}>
        {open ? 'Hide guardians' : 'Guardians'}
      </button>
      {open && (
        <div className="guardians-panel-body">
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {guardians && guardians.length === 0 && (
            <p className="status">No parent account can see {student.full_name} yet.</p>
          )}
          {guardians && guardians.length > 0 && (
            <ul>
              {guardians.map((g) => (
                <li key={g.user_id}>
                  {g.full_name} ({g.email}){' '}
                  <button
                    type="button"
                    className="btn-danger"
                    disabled={isBusy}
                    onClick={() =>
                      void run(
                        () => api.unlinkGuardian(student.id, g.user_id),
                        'Failed to unlink guardian.',
                      )
                    }
                  >
                    Unlink
                  </button>
                </li>
              ))}
            </ul>
          )}
          {guardians && (
            <div className="guardians-panel-link">
              <label htmlFor={`guardian-choice-${student.id}`}>Link a parent account</label>
              <select
                id={`guardian-choice-${student.id}`}
                value={choice}
                onChange={(event) => setChoice(event.target.value)}
              >
                <option value="">Select a parent</option>
                {linkable.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.full_name} ({p.email})
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={!choice || isBusy}
                onClick={() =>
                  void run(async () => {
                    await api.linkGuardian(student.id, Number(choice))
                    setChoice('')
                  }, 'Failed to link guardian.')
                }
              >
                Link guardian
              </button>
              {linkable.length === 0 && (
                <p className="status">
                  No other parent accounts. Create one on the Users page with the parent role.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function StudentsSection({
  students,
  schools,
  stops,
  qualifications = [],
  canEdit,
  onChanged,
}: {
  students: Student[]
  schools: School[]
  stops: Stop[]
  // Vehicle capabilities a student may need (spec section 3 accommodations).
  qualifications?: Qualification[]
  canEdit: boolean
  onChanged: () => Promise<void>
}) {
  const accommodationOptions = qualifications.filter(
    (q) => q.kind === 'vehicle_capability' && q.is_active !== false,
  )
  const schoolsById = new Map(schools.map((s) => [s.id, s]))
  const stopsById = new Map(stops.map((s) => [s.id, s]))

  // --- Create form ---
  const [name, setName] = useState('')
  const [schoolId, setSchoolId] = useState('')
  const [stopId, setStopId] = useState('')
  const [defaultRidership, setDefaultRidership] = useState<RidershipDefault>('rides')
  const [grade, setGrade] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [isSavingCreate, setIsSavingCreate] = useState(false)

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    setCreateError(null)
    setIsSavingCreate(true)
    try {
      await api.createStudent({
        full_name: name,
        school_id: Number(schoolId),
        stop_id: stopId ? Number(stopId) : undefined,
        default_ridership: defaultRidership,
        grade: grade || null,
      })
      setName('')
      setGrade('')
      setSchoolId('')
      setStopId('')
      setDefaultRidership('rides')
      await onChanged()
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create student.')
    } finally {
      setIsSavingCreate(false)
    }
  }

  // --- Edit ("reassign") ---
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draftName, setDraftName] = useState('')
  const [draftSchoolId, setDraftSchoolId] = useState('')
  const [draftStopId, setDraftStopId] = useState('')
  const [draftRidership, setDraftRidership] = useState<RidershipDefault>('rides')
  const [draftGrade, setDraftGrade] = useState('')
  const [draftSpecialized, setDraftSpecialized] = useState(false)
  const [draftHazardous, setDraftHazardous] = useState(false)
  const [draftAccommodations, setDraftAccommodations] = useState<Set<string>>(new Set())
  const [rowError, setRowError] = useState<string | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)

  function startEdit(student: Student) {
    setEditingId(student.id)
    setDraftName(student.full_name)
    setDraftSchoolId(String(student.school_id))
    setDraftStopId(student.stop_id != null ? String(student.stop_id) : '')
    setDraftRidership(student.default_ridership)
    setDraftGrade(student.grade ?? '')
    setDraftSpecialized(Boolean(student.needs_specialized_transport))
    setDraftHazardous(Boolean(student.hazardous_route))
    setDraftAccommodations(new Set((student.accommodations ?? []).map((q) => q.code)))
    setRowError(null)
  }

  function toggleAccommodation(code: string, on: boolean) {
    setDraftAccommodations((prev) => {
      const next = new Set(prev)
      if (on) next.add(code)
      else next.delete(code)
      return next
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setRowError(null)
  }

  async function handleSaveEdit(event: FormEvent, student: Student) {
    event.preventDefault()
    setRowError(null)
    setIsSavingEdit(true)
    try {
      await api.updateStudent(student.id, {
        // SIS-imported students' name and school are owned by the SIS.
        ...(student.external_id
          ? {}
          : {
              full_name: draftName,
              school_id: Number(draftSchoolId),
              grade: draftGrade || null,
            }),
        stop_id: draftStopId ? Number(draftStopId) : null,
        default_ridership: draftRidership,
        needs_specialized_transport: draftSpecialized,
        hazardous_route: draftHazardous,
        accommodation_codes: [...draftAccommodations].sort(),
      })
      cancelEdit()
      await onChanged()
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : 'Failed to save student.')
    } finally {
      setIsSavingEdit(false)
    }
  }

  return (
    <section className="students-section">
      <h2>Students</h2>
      {rowError && (
        <p role="alert" className="error">
          {rowError}
        </p>
      )}
      <ul>
        {students.map((s) => {
          const fromSis = Boolean(s.external_id)
          return editingId === s.id ? (
            <li key={s.id}>
              <form onSubmit={(event) => void handleSaveEdit(event, s)}>
                {fromSis && (
                  <p className="status">
                    Name, school and grade come from the SIS roster; change them there and
                    re-import.
                  </p>
                )}
                <label htmlFor={`student-edit-name-${s.id}`}>Student&apos;s name</label>
                <input
                  id={`student-edit-name-${s.id}`}
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  disabled={fromSis}
                  required
                />
                <label htmlFor={`student-edit-school-${s.id}`}>Student&apos;s school</label>
                <select
                  id={`student-edit-school-${s.id}`}
                  value={draftSchoolId}
                  onChange={(event) => setDraftSchoolId(event.target.value)}
                  disabled={fromSis}
                >
                  {schools.map((school) => (
                    <option key={school.id} value={school.id}>
                      {school.name}
                    </option>
                  ))}
                </select>
                <label htmlFor={`student-edit-grade-${s.id}`}>Student&apos;s grade</label>
                <select
                  id={`student-edit-grade-${s.id}`}
                  value={draftGrade}
                  onChange={(event) => setDraftGrade(event.target.value)}
                  disabled={fromSis}
                >
                  <option value="">Not set</option>
                  {GRADES.map((g) => (
                    <option key={g} value={g}>
                      {gradeLabel(g)}
                    </option>
                  ))}
                </select>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={draftSpecialized}
                    onChange={(event) => setDraftSpecialized(event.target.checked)}
                  />
                  Receives specialized transportation
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={draftHazardous}
                    onChange={(event) => setDraftHazardous(event.target.checked)}
                  />
                  Hazardous walking route (eligible at any distance)
                </label>
                {accommodationOptions.length > 0 && (
                  <fieldset className="student-accommodations">
                    <legend>Needs on the bus</legend>
                    {accommodationOptions.map((q) => (
                      <label key={q.code} className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={draftAccommodations.has(q.code)}
                          onChange={(event) => toggleAccommodation(q.code, event.target.checked)}
                        />
                        {q.description || q.code}
                      </label>
                    ))}
                  </fieldset>
                )}
                <label htmlFor={`student-edit-stop-${s.id}`}>Student&apos;s stop</label>
                <select
                  id={`student-edit-stop-${s.id}`}
                  value={draftStopId}
                  onChange={(event) => setDraftStopId(event.target.value)}
                >
                  <option value="">Not yet assigned</option>
                  {stops.map((stop) => (
                    <option key={stop.id} value={stop.id}>
                      {stop.label}
                    </option>
                  ))}
                </select>
                <label htmlFor={`student-edit-ridership-${s.id}`}>
                  Student&apos;s default ridership
                </label>
                <select
                  id={`student-edit-ridership-${s.id}`}
                  value={draftRidership}
                  onChange={(event) => setDraftRidership(event.target.value as RidershipDefault)}
                >
                  <option value="rides">Rides every school day</option>
                  <option value="does_not_ride">Does not ride unless requested</option>
                </select>
                <button type="submit" disabled={isSavingEdit}>
                  {isSavingEdit ? 'Saving…' : 'Save'}
                </button>
                <button type="button" onClick={cancelEdit} disabled={isSavingEdit}>
                  Cancel
                </button>
              </form>
            </li>
          ) : (
            <li key={s.id}>
              {s.full_name} — {schoolsById.get(s.school_id)?.name ?? `School ${s.school_id}`}
              {s.stop_id != null && ` (${stopsById.get(s.stop_id)?.label ?? `Stop ${s.stop_id}`})`}
              {' — default: '}
              {s.default_ridership === 'rides' ? 'rides' : 'does not ride'}
              {' — '}
              {gradeLabel(s.grade)}{' '}
              {s.eligibility && (
                <span title={s.eligibility.reason}>
                  <Badge tone={s.eligibility.eligible ? 'success' : 'neutral'}>
                    {s.eligibility.eligible ? 'Eligible' : 'Not eligible'}
                  </Badge>{' '}
                  <span className="student-eligibility-reason">{s.eligibility.reason}</span>
                </span>
              )}{' '}
              {(s.accommodations ?? []).map((q) => (
                <Badge key={q.code} tone="info">
                  {q.description || q.code}
                </Badge>
              ))}{' '}
              {fromSis && <Badge tone="info">From SIS</Badge>}
              {canEdit && (
                <span className="students-section-actions">
                  <button
                    type="button"
                    onClick={() => startEdit(s)}
                    aria-label={`Edit ${s.full_name}`}
                  >
                    Edit
                  </button>
                  <GuardiansPanel student={s} />
                  <StudentHomePanel
                    student={s}
                    school={schoolsById.get(s.school_id)}
                    onChanged={onChanged}
                  />
                </span>
              )}
            </li>
          )
        })}
      </ul>
      {canEdit && (
        <form onSubmit={(event) => void handleCreate(event)}>
          <label htmlFor="student-name">Student name</label>
          <input
            id="student-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
          <label htmlFor="student-school">School</label>
          <select
            id="student-school"
            value={schoolId}
            onChange={(event) => setSchoolId(event.target.value)}
            required
          >
            <option value="">Select a school</option>
            {schools.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <label htmlFor="student-grade">Grade (optional)</label>
          <select
            id="student-grade"
            value={grade}
            onChange={(event) => setGrade(event.target.value)}
          >
            <option value="">Not set</option>
            {GRADES.map((g) => (
              <option key={g} value={g}>
                {gradeLabel(g)}
              </option>
            ))}
          </select>
          <label htmlFor="student-stop">Stop (optional)</label>
          <select
            id="student-stop"
            value={stopId}
            onChange={(event) => setStopId(event.target.value)}
          >
            <option value="">Not yet assigned</option>
            {stops.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          <label htmlFor="student-default-ridership">Default ridership</label>
          <select
            id="student-default-ridership"
            value={defaultRidership}
            onChange={(event) => setDefaultRidership(event.target.value as RidershipDefault)}
          >
            <option value="rides">Rides every school day</option>
            <option value="does_not_ride">Does not ride unless requested</option>
          </select>
          {createError && (
            <p role="alert" className="error">
              {createError}
            </p>
          )}
          <button type="submit" disabled={isSavingCreate}>
            {isSavingCreate ? 'Saving…' : 'Add student'}
          </button>
        </form>
      )}
    </section>
  )
}
