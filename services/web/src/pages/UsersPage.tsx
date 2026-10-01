import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { Driver, ResetLink, Role, School, Student, User } from '../api/types'
import { Badge } from '../components/Badge'

// spec section 17: "User permissions" is a Transportation Administrator
// responsibility, not a dispatcher one -- narrower than the rest of the
// admin console's schools/vehicles/drivers screens.
const ROLES: Role[] = [
  'driver',
  'student',
  'parent',
  'school_admin',
  'dispatcher',
  'transportation_admin',
]

interface LinkFields {
  driver_id: string
  school_id: string
  student_id: string
}

function emptyLinks(): LinkFields {
  return { driver_id: '', school_id: '', student_id: '' }
}

function linksFor(u: User): LinkFields {
  return {
    driver_id: u.driver_id != null ? String(u.driver_id) : '',
    school_id: u.school_id != null ? String(u.school_id) : '',
    student_id: u.student_id != null ? String(u.student_id) : '',
  }
}

function LinkFieldsetFor({
  role,
  links,
  idPrefix,
  drivers,
  schools,
  students,
  onChange,
}: {
  role: Role
  links: LinkFields
  idPrefix: string
  drivers: Driver[]
  schools: School[]
  students: Student[]
  onChange: (next: LinkFields) => void
}) {
  if (role === 'driver') {
    return (
      <>
        <label htmlFor={`${idPrefix}-driver`}>Linked driver record</label>
        <select
          id={`${idPrefix}-driver`}
          value={links.driver_id}
          onChange={(event) => onChange({ ...links, driver_id: event.target.value })}
        >
          <option value="">Not linked</option>
          {drivers.map((d) => (
            <option key={d.id} value={d.id}>
              {d.full_name}
            </option>
          ))}
        </select>
      </>
    )
  }
  if (role === 'school_admin') {
    return (
      <>
        <label htmlFor={`${idPrefix}-school`}>School</label>
        <select
          id={`${idPrefix}-school`}
          value={links.school_id}
          onChange={(event) => onChange({ ...links, school_id: event.target.value })}
        >
          <option value="">Not linked</option>
          {schools.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </>
    )
  }
  if (role === 'student') {
    return (
      <>
        <label htmlFor={`${idPrefix}-student`}>Linked student record</label>
        <select
          id={`${idPrefix}-student`}
          value={links.student_id}
          onChange={(event) => onChange({ ...links, student_id: event.target.value })}
        >
          <option value="">Not linked</option>
          {students.map((s) => (
            <option key={s.id} value={s.id}>
              {s.full_name}
            </option>
          ))}
        </select>
      </>
    )
  }
  return null
}

export function UsersPage() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [schools, setSchools] = useState<School[]>([])
  const [students, setStudents] = useState<Student[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [emailEnabled, setEmailEnabled] = useState(false)

  useEffect(() => {
    let current = true
    api.getAuthOptions().then(
      (options) => {
        if (current) setEmailEnabled(options.email_enabled)
      },
      () => {
        // Without it, admins type a password, as before email existed.
      },
    )
    return () => {
      current = false
    }
  }, [])

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      const [usersData, driversData, schoolsData, studentsData] = await Promise.all([
        api.getUsers(),
        api.getDrivers(),
        api.getSchools(),
        api.getStudents(),
      ])
      setUsers(usersData)
      setDrivers(driversData)
      setSchools(schoolsData)
      setStudents(studentsData)
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : 'Failed to load users.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const driversById = new Map(drivers.map((d) => [d.id, d]))
  const schoolsById = new Map(schools.map((s) => [s.id, s]))
  const studentsById = new Map(students.map((s) => [s.id, s]))

  function linkedRecordLabel(u: User): string | null {
    if (u.driver_id != null)
      return driversById.get(u.driver_id)?.full_name ?? `Driver #${u.driver_id}`
    if (u.school_id != null) return schoolsById.get(u.school_id)?.name ?? `School #${u.school_id}`
    if (u.student_id != null)
      return studentsById.get(u.student_id)?.full_name ?? `Student #${u.student_id}`
    return null
  }

  // --- Create form ---
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<Role>('dispatcher')
  const [links, setLinks] = useState<LinkFields>(emptyLinks())
  const [createError, setCreateError] = useState<string | null>(null)
  const [sendSetup, setSendSetup] = useState(true)
  const [createdNotice, setCreatedNotice] = useState<string | null>(null)
  const setupByEmail = emailEnabled && sendSetup
  const [isSavingCreate, setIsSavingCreate] = useState(false)

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    setCreateError(null)
    setCreatedNotice(null)
    setIsSavingCreate(true)
    try {
      await api.createUser({
        email,
        password: setupByEmail ? undefined : password,
        full_name: fullName,
        role,
        driver_id: links.driver_id ? Number(links.driver_id) : undefined,
        school_id: links.school_id ? Number(links.school_id) : undefined,
        student_id: links.student_id ? Number(links.student_id) : undefined,
      })
      setCreatedNotice(
        setupByEmail
          ? `Account created. ${email} has been emailed a link to choose a password.`
          : `Account created for ${email}.`,
      )
      setEmail('')
      setPassword('')
      setFullName('')
      setRole('dispatcher')
      setLinks(emptyLinks())
      await load()
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create user.')
    } finally {
      setIsSavingCreate(false)
    }
  }

  // --- Edit ---
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editRole, setEditRole] = useState<Role>('dispatcher')
  const [editLinks, setEditLinks] = useState<LinkFields>(emptyLinks())
  const [rowError, setRowError] = useState<string | null>(null)
  const [isSavingEdit, setIsSavingEdit] = useState(false)
  const [togglingId, setTogglingId] = useState<number | null>(null)

  function startEdit(u: User) {
    setEditingId(u.id)
    setEditRole(u.role)
    setEditLinks(linksFor(u))
    setRowError(null)
  }

  function cancelEdit() {
    setEditingId(null)
    setRowError(null)
  }

  async function handleSaveEdit(event: FormEvent) {
    event.preventDefault()
    if (editingId === null) return
    setRowError(null)
    setIsSavingEdit(true)
    try {
      await api.updateUser(editingId, {
        role: editRole,
        driver_id: editLinks.driver_id ? Number(editLinks.driver_id) : undefined,
        school_id: editLinks.school_id ? Number(editLinks.school_id) : undefined,
        student_id: editLinks.student_id ? Number(editLinks.student_id) : undefined,
      })
      cancelEdit()
      await load()
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : 'Failed to save user.')
    } finally {
      setIsSavingEdit(false)
    }
  }

  // --- Reset links ---
  const [resetFor, setResetFor] = useState<{ user: User; link: ResetLink } | null>(null)
  const [copied, setCopied] = useState(false)
  const [issuingId, setIssuingId] = useState<number | null>(null)

  async function handleIssueResetLink(u: User) {
    setRowError(null)
    setCopied(false)
    setIssuingId(u.id)
    try {
      setResetFor({ user: u, link: await api.issueResetLink(u.id) })
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : 'Failed to create a reset link.')
    } finally {
      setIssuingId(null)
    }
  }

  const resetUrl = resetFor ? `${window.location.origin}${resetFor.link.reset_path}` : ''

  async function copyResetUrl() {
    try {
      await navigator.clipboard.writeText(resetUrl)
      setCopied(true)
    } catch {
      setRowError('Copying failed. Select the link and copy it.')
    }
  }

  const [resettingMfaId, setResettingMfaId] = useState<number | null>(null)
  const [unlinkingId, setUnlinkingId] = useState<number | null>(null)

  async function handleUnlinkSso(u: User) {
    if (
      !window.confirm(
        `Unlink ${u.full_name}'s district account? Their next district sign-in will link again, to whichever district account uses ${u.email}.`,
      )
    ) {
      return
    }
    setRowError(null)
    setUnlinkingId(u.id)
    try {
      await api.unlinkSso(u.id)
      await load()
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : 'Failed to unlink the district account.')
    } finally {
      setUnlinkingId(null)
    }
  }

  async function handleResetMfa(u: User) {
    if (
      !window.confirm(
        `Reset two-step sign-in for ${u.full_name}? They'll be signed out everywhere and set it up again at their next sign-in.`,
      )
    ) {
      return
    }
    setRowError(null)
    setResettingMfaId(u.id)
    try {
      await api.resetUserMfa(u.id)
      await load()
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : 'Failed to reset two-step sign-in.')
    } finally {
      setResettingMfaId(null)
    }
  }

  async function handleToggleActive(u: User) {
    setRowError(null)
    setTogglingId(u.id)
    try {
      await api.updateUser(u.id, { is_active: !u.is_active })
      await load()
    } catch (err) {
      setRowError(err instanceof ApiError ? err.message : 'Failed to update user.')
    } finally {
      setTogglingId(null)
    }
  }

  return (
    <main className="users-page">
      <h1>Users</h1>
      <p>
        Create accounts and manage role/permissions (spec section 17). You never set someone
        else&apos;s password: for a forgotten one, create a reset link and pass it on privately.
      </p>
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {rowError && (
        <p role="alert" className="error">
          {rowError}
        </p>
      )}

      {resetFor && (
        <div className="reset-link-panel" role="region" aria-label="Reset link">
          <p>
            <strong>Reset link for {resetFor.user.full_name}</strong>: works once, until{' '}
            {new Date(resetFor.link.expires_at).toLocaleString()}. Share it privately: whoever has
            it can set this account&apos;s password. It won&apos;t be shown again.
          </p>
          <input
            readOnly
            aria-label="Reset link address"
            value={resetUrl}
            onFocus={(event) => event.target.select()}
          />
          <button type="button" onClick={() => void copyResetUrl()}>
            {copied ? 'Copied' : 'Copy'}
          </button>{' '}
          <button type="button" onClick={() => setResetFor(null)}>
            Done
          </button>
        </div>
      )}

      <table>
        <thead>
          <tr>
            <th>Email</th>
            <th>Name</th>
            <th>Role</th>
            <th>Linked record</th>
            <th>Status</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {users.map((u) =>
            editingId === u.id ? (
              <tr key={u.id}>
                <td colSpan={6}>
                  <form onSubmit={(event) => void handleSaveEdit(event)}>
                    <label htmlFor={`user-edit-role-${u.id}`}>Role</label>
                    <select
                      id={`user-edit-role-${u.id}`}
                      value={editRole}
                      onChange={(event) => {
                        setEditRole(event.target.value as Role)
                        setEditLinks(emptyLinks())
                      }}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                    <LinkFieldsetFor
                      role={editRole}
                      links={editLinks}
                      idPrefix={`user-edit-${u.id}`}
                      drivers={drivers}
                      schools={schools}
                      students={students}
                      onChange={setEditLinks}
                    />
                    <button type="submit" disabled={isSavingEdit}>
                      {isSavingEdit ? 'Saving…' : 'Save'}
                    </button>
                    <button type="button" onClick={cancelEdit} disabled={isSavingEdit}>
                      Cancel
                    </button>
                  </form>
                </td>
              </tr>
            ) : (
              <tr key={u.id}>
                <td>{u.email}</td>
                <td>{u.full_name}</td>
                <td>{u.role}</td>
                <td>{linkedRecordLabel(u) ?? '—'}</td>
                <td>
                  <Badge tone={u.is_active ? 'success' : 'neutral'}>
                    {u.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                  {u.mfa_enabled && (
                    <>
                      {' '}
                      <Badge tone="info">2-step on</Badge>
                    </>
                  )}
                  {u.sso_linked && (
                    <>
                      {' '}
                      <Badge tone="info">District sign-in</Badge>
                    </>
                  )}
                </td>
                <td>
                  <button type="button" onClick={() => startEdit(u)}>
                    Edit
                  </button>{' '}
                  {u.sso_linked && (
                    <>
                      <button
                        type="button"
                        onClick={() => void handleUnlinkSso(u)}
                        disabled={unlinkingId === u.id}
                      >
                        Unlink district sign-in
                      </button>{' '}
                    </>
                  )}
                  {u.mfa_enabled && u.id !== me?.id && (
                    <>
                      <button
                        type="button"
                        onClick={() => void handleResetMfa(u)}
                        disabled={resettingMfaId === u.id}
                      >
                        Reset 2-step
                      </button>{' '}
                    </>
                  )}
                  {u.is_active && (
                    <>
                      <button
                        type="button"
                        onClick={() => void handleIssueResetLink(u)}
                        disabled={issuingId === u.id}
                      >
                        Reset link
                      </button>{' '}
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => void handleToggleActive(u)}
                    disabled={togglingId === u.id || u.id === me?.id}
                    title={u.id === me?.id ? 'You cannot deactivate your own account' : undefined}
                  >
                    {u.is_active ? 'Deactivate' : 'Reactivate'}
                  </button>
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>

      <h2>Add user</h2>
      <form onSubmit={(event) => void handleCreate(event)}>
        <label htmlFor="user-email">Email</label>
        <input
          id="user-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        {emailEnabled && (
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={sendSetup}
              onChange={(event) => setSendSetup(event.target.checked)}
            />{' '}
            Email them a link to choose their own password
          </label>
        )}
        {!setupByEmail && (
          <>
            <label htmlFor="user-password">Password</label>
            <input
              id="user-password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </>
        )}
        <label htmlFor="user-full-name">Full name</label>
        <input
          id="user-full-name"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          required
        />
        <label htmlFor="user-role">Role</label>
        <select
          id="user-role"
          value={role}
          onChange={(event) => {
            setRole(event.target.value as Role)
            setLinks(emptyLinks())
          }}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <LinkFieldsetFor
          role={role}
          links={links}
          idPrefix="user-create"
          drivers={drivers}
          schools={schools}
          students={students}
          onChange={setLinks}
        />
        {createError && (
          <p role="alert" className="error">
            {createError}
          </p>
        )}
        {createdNotice && (
          <p role="status" className="status">
            {createdNotice}
          </p>
        )}
        <button type="submit" disabled={isSavingCreate}>
          {isSavingCreate ? 'Saving…' : 'Add user'}
        </button>
      </form>
    </main>
  )
}
