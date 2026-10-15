import { useCallback, useEffect, useState, type FormEvent } from 'react'
import * as api from '../api/client'
import { ApiError } from '../api/client'
import type {
  BellCalendarDay,
  BellChange,
  BellImport,
  BellOffsets,
  BellSchedule,
  School,
  SchoolBells,
} from '../api/types'
import { Badge } from '../components/Badge'

/**
 * School bell schedules (services/api/src/isd_api/bells.py): each school's
 * Regular bells and named alternates, the days that use an alternate, and
 * how long before and after the bells buses arrive and leave. Routes that
 * follow the bells (Templates page) take their window from these, so a
 * change here moves the upcoming runs that haven't started.
 */

function toTime(minute: number): string {
  return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
}

function toMinute(time: string): number {
  const [h, m] = time.split(':').map(Number)
  return h * 60 + m
}

function describe(change: BellChange): string {
  const parts = ['Saved.']
  if (change.runs_updated > 0) {
    parts.push(
      change.runs_updated === 1
        ? '1 upcoming run moved to the new bell times.'
        : `${change.runs_updated} upcoming runs moved to the new bell times.`,
    )
  }
  if (change.assigned_runs_moved > 0) {
    parts.push(
      `${change.assigned_runs_moved} of them already had a bus: check Needs attention on the Schedule page and run the schedule again for those days.`,
    )
  }
  if (change.skipped_schools.length > 0) {
    parts.push(`No schedule by that name at: ${change.skipped_schools.join(', ')}.`)
  }
  return parts.join(' ')
}

const OFFSET_FIELDS: { key: keyof BellOffsets; label: string }[] = [
  {
    key: 'arrive_earliest_before',
    label: 'Arrive at the earliest (minutes before the first bell)',
  },
  { key: 'arrive_latest_before', label: 'Arrive at the latest (minutes before the first bell)' },
  { key: 'leave_earliest_after', label: 'Leave at the earliest (minutes after dismissal)' },
  { key: 'leave_latest_after', label: 'Leave at the latest (minutes after dismissal)' },
]

type OffsetDraft = Record<keyof BellOffsets, string>

function draftOf(offsets: BellOffsets): OffsetDraft {
  return {
    arrive_earliest_before: String(offsets.arrive_earliest_before),
    arrive_latest_before: String(offsets.arrive_latest_before),
    leave_earliest_after: String(offsets.leave_earliest_after),
    leave_latest_after: String(offsets.leave_latest_after),
  }
}

function offsetsOf(draft: OffsetDraft): BellOffsets {
  return {
    arrive_earliest_before: Number(draft.arrive_earliest_before),
    arrive_latest_before: Number(draft.arrive_latest_before),
    leave_earliest_after: Number(draft.leave_earliest_after),
    leave_latest_after: Number(draft.leave_latest_after),
  }
}

function OffsetInputs({
  idPrefix,
  draft,
  disabled,
  onChange,
}: {
  idPrefix: string
  draft: OffsetDraft
  disabled: boolean
  onChange: (draft: OffsetDraft) => void
}) {
  return (
    <>
      {OFFSET_FIELDS.map(({ key, label }) => (
        <div key={key}>
          <label htmlFor={`${idPrefix}-${key}`}>{label}</label>
          <input
            id={`${idPrefix}-${key}`}
            type="number"
            min="0"
            max="180"
            value={draft[key]}
            disabled={disabled}
            onChange={(event) => onChange({ ...draft, [key]: event.target.value })}
            required
          />
        </div>
      ))}
    </>
  )
}

export function BellSchedulesSection({
  schools,
  canEdit,
}: {
  schools: School[]
  canEdit: boolean
}) {
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  // --- The district's windows ---
  const [districtDraft, setDistrictDraft] = useState<OffsetDraft | null>(null)
  const [districtIsDefault, setDistrictIsDefault] = useState(true)

  // --- One school ---
  const [pickedSchoolId, setSchoolId] = useState('')
  // Until someone picks one, the first school.
  const schoolId = pickedSchoolId || (schools.length > 0 ? String(schools[0].id) : '')
  const [loadedBells, setBells] = useState<SchoolBells | null>(null)
  // Only once the picked school's have arrived.
  const bells = loadedBells?.school_id === Number(schoolId) ? loadedBells : null
  const [ownDraft, setOwnDraft] = useState<OffsetDraft | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editFirst, setEditFirst] = useState('')
  const [editDismissal, setEditDismissal] = useState('')
  const [newName, setNewName] = useState('')
  const [newFirst, setNewFirst] = useState('')
  const [newDismissal, setNewDismissal] = useState('')

  // --- Special days ---
  const [days, setDays] = useState<BellCalendarDay[]>([])
  const [dayDate, setDayDate] = useState('')
  const [dayName, setDayName] = useState('')
  const [dayScope, setDayScope] = useState<'all' | 'school'>('all')

  // --- CSV import ---
  const [csv, setCsv] = useState('')
  const [preview, setPreview] = useState<BellImport | null>(null)

  const loadDistrict = useCallback(async () => {
    const rules = await api.getBellRules()
    setDistrictDraft(draftOf(rules))
    setDistrictIsDefault(rules.is_default)
  }, [])

  const loadSchool = useCallback(async (id: string) => {
    if (!id) return
    const read = await api.getSchoolBells(Number(id))
    setBells(read)
    setOwnDraft(read.own_offsets ? draftOf(read.own_offsets) : null)
  }, [])

  const loadDays = useCallback(async () => {
    setDays(await api.getBellCalendar())
  }, [])

  useEffect(() => {
    let current = true
    Promise.all([api.getBellRules(), api.getBellCalendar()]).then(
      ([rules, calendar]) => {
        if (!current) return
        setDistrictDraft(draftOf(rules))
        setDistrictIsDefault(rules.is_default)
        setDays(calendar)
      },
      (err: unknown) => {
        if (current) {
          setError(err instanceof ApiError ? err.message : 'Failed to load bell schedules.')
        }
      },
    )
    return () => {
      current = false
    }
  }, [])

  useEffect(() => {
    if (!schoolId) return
    let current = true
    api.getSchoolBells(Number(schoolId)).then(
      (read) => {
        if (!current) return
        setBells(read)
        setOwnDraft(read.own_offsets ? draftOf(read.own_offsets) : null)
      },
      (err: unknown) => {
        if (current) {
          setError(err instanceof ApiError ? err.message : 'Failed to load bell schedules.')
        }
      },
    )
    return () => {
      current = false
    }
  }, [schoolId])

  // Runs a change, then reloads what it can have touched.
  async function save(action: () => Promise<BellChange | void>) {
    setError(null)
    setMessage(null)
    setIsSaving(true)
    try {
      const change = await action()
      setMessage(change ? describe(change) : 'Saved.')
      await Promise.all([loadDistrict(), loadSchool(schoolId), loadDays()])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save.')
    } finally {
      setIsSaving(false)
    }
  }

  function handleDistrict(event: FormEvent) {
    event.preventDefault()
    if (districtDraft) void save(() => api.updateBellRules(offsetsOf(districtDraft)))
  }

  function handleOwn(event: FormEvent) {
    event.preventDefault()
    if (bells && ownDraft) {
      void save(() => api.setSchoolBellOffsets(bells.school_id, offsetsOf(ownDraft)))
    }
  }

  function handleUseDistrict(useDistrict: boolean) {
    if (!bells) return
    if (useDistrict) {
      if (bells.own_offsets) void save(() => api.setSchoolBellOffsets(bells.school_id, null))
      else setOwnDraft(null)
    } else {
      setOwnDraft(draftOf(bells.offsets_in_use))
    }
  }

  function handleAdd(event: FormEvent) {
    event.preventDefault()
    if (!bells) return
    void save(async () => {
      await api.createBellSchedule(bells.school_id, {
        name: newName,
        first_bell_minute: toMinute(newFirst),
        dismissal_minute: toMinute(newDismissal),
      })
      setNewName('')
      setNewFirst('')
      setNewDismissal('')
    })
  }

  function startEdit(schedule: BellSchedule) {
    setEditingId(schedule.id)
    setEditFirst(toTime(schedule.first_bell_minute))
    setEditDismissal(toTime(schedule.dismissal_minute))
  }

  function handleEdit(event: FormEvent, schedule: BellSchedule) {
    event.preventDefault()
    void save(async () => {
      const change = await api.updateBellSchedule(schedule.id, {
        first_bell_minute: toMinute(editFirst),
        dismissal_minute: toMinute(editDismissal),
      })
      setEditingId(null)
      return change
    })
  }

  function handleDay(event: FormEvent) {
    event.preventDefault()
    void save(async () => {
      const change = await api.setBellCalendarDay(
        dayDate,
        dayName,
        dayScope === 'school' && bells ? [bells.school_id] : null,
      )
      setDayDate('')
      return change
    })
  }

  async function handlePreview(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setMessage(null)
    setIsSaving(true)
    try {
      setPreview(await api.importBellSchedules(csv, false))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to read the CSV.')
    } finally {
      setIsSaving(false)
    }
  }

  function handleApply() {
    void save(async () => {
      const result = await api.importBellSchedules(csv, true)
      setPreview(result)
      return result.change ?? undefined
    })
  }

  async function handleFile(file: File | undefined) {
    if (file) {
      setCsv(await file.text())
      setPreview(null)
    }
  }

  const scheduleNames = [
    ...new Set([
      ...(bells?.schedules ?? []).map((s) => s.name),
      ...days.map((d) => d.schedule_name),
    ]),
  ]

  return (
    <section className="bell-schedules-section">
      <h2>Bell schedules</h2>
      <p>
        Each school&apos;s bell times. Routes that follow the bells (Templates page) take their
        window from them, so an early-release day moves that day&apos;s buses. Changing bells moves
        the runs already made for today and later that haven&apos;t started.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="status">
          {message}
        </p>
      )}

      <h3>Bus windows around the bells</h3>
      <p>
        For the whole district{districtIsDefault ? ' (the defaults)' : ''}. A school can set its own
        below.
      </p>
      {districtDraft && (
        <form onSubmit={handleDistrict}>
          <OffsetInputs
            idPrefix="district"
            draft={districtDraft}
            disabled={!canEdit}
            onChange={setDistrictDraft}
          />
          {canEdit && (
            <button type="submit" disabled={isSaving}>
              Save district windows
            </button>
          )}
        </form>
      )}

      <h3>A school&apos;s bells</h3>
      <label htmlFor="bells-school">Show the bells of</label>
      <select
        id="bells-school"
        value={schoolId}
        onChange={(event) => {
          setSchoolId(event.target.value)
          setEditingId(null)
        }}
      >
        {schools.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>

      {bells && (
        <>
          {bells.schedules.length === 0 ? (
            <p>No bell times for {bells.school_name} yet.</p>
          ) : (
            <table>
              <caption>Bell schedules at {bells.school_name}</caption>
              <thead>
                <tr>
                  <th scope="col">Schedule</th>
                  <th scope="col">First bell</th>
                  <th scope="col">Dismissal</th>
                  {canEdit && <th scope="col">Actions</th>}
                </tr>
              </thead>
              <tbody>
                {bells.schedules.map((s) =>
                  editingId === s.id ? (
                    <tr key={s.id}>
                      <td>{s.name}</td>
                      <td colSpan={canEdit ? 3 : 2}>
                        <form className="inline-form" onSubmit={(event) => handleEdit(event, s)}>
                          <label htmlFor={`bell-edit-first-${s.id}`}>{s.name}: first bell</label>
                          <input
                            id={`bell-edit-first-${s.id}`}
                            type="time"
                            value={editFirst}
                            onChange={(event) => setEditFirst(event.target.value)}
                            required
                          />
                          <label htmlFor={`bell-edit-dismissal-${s.id}`}>{s.name}: dismissal</label>
                          <input
                            id={`bell-edit-dismissal-${s.id}`}
                            type="time"
                            value={editDismissal}
                            onChange={(event) => setEditDismissal(event.target.value)}
                            required
                          />
                          <button type="submit" disabled={isSaving}>
                            Save {s.name}
                          </button>{' '}
                          <button type="button" onClick={() => setEditingId(null)}>
                            Cancel
                          </button>
                        </form>
                      </td>
                    </tr>
                  ) : (
                    <tr key={s.id}>
                      <td>
                        {s.name} {s.is_regular && <Badge tone="info">Regular</Badge>}
                      </td>
                      <td>{toTime(s.first_bell_minute)}</td>
                      <td>{toTime(s.dismissal_minute)}</td>
                      {canEdit && (
                        <td>
                          <button type="button" onClick={() => startEdit(s)}>
                            Edit {s.name}
                          </button>{' '}
                          {!s.is_regular && (
                            <>
                              <button
                                type="button"
                                disabled={isSaving}
                                onClick={() =>
                                  void save(() =>
                                    api.updateBellSchedule(s.id, { is_regular: true }),
                                  )
                                }
                              >
                                Make {s.name} regular
                              </button>{' '}
                              <button
                                type="button"
                                disabled={isSaving}
                                onClick={() => void save(() => api.deleteBellSchedule(s.id))}
                              >
                                Delete {s.name}
                              </button>
                            </>
                          )}
                        </td>
                      )}
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          )}

          {canEdit && (
            <form onSubmit={handleAdd}>
              <h4>Add a schedule</h4>
              <label htmlFor="bell-new-name">Name (e.g. Regular, Early release)</label>
              <input
                id="bell-new-name"
                maxLength={60}
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                required
              />
              <label htmlFor="bell-new-first">First bell</label>
              <input
                id="bell-new-first"
                type="time"
                value={newFirst}
                onChange={(event) => setNewFirst(event.target.value)}
                required
              />
              <label htmlFor="bell-new-dismissal">Dismissal</label>
              <input
                id="bell-new-dismissal"
                type="time"
                value={newDismissal}
                onChange={(event) => setNewDismissal(event.target.value)}
                required
              />
              <button type="submit" disabled={isSaving}>
                Add schedule
              </button>
            </form>
          )}

          <h4>{bells.school_name}&apos;s bus windows</h4>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={ownDraft === null}
              disabled={!canEdit || isSaving}
              onChange={(event) => handleUseDistrict(event.target.checked)}
            />{' '}
            Use the district&apos;s bus windows
          </label>
          {ownDraft && (
            <form onSubmit={handleOwn}>
              <OffsetInputs
                idPrefix="school"
                draft={ownDraft}
                disabled={!canEdit}
                onChange={setOwnDraft}
              />
              {canEdit && (
                <button type="submit" disabled={isSaving}>
                  Save {bells.school_name}&apos;s windows
                </button>
              )}
            </form>
          )}
        </>
      )}

      <h3>Special days</h3>
      {days.length === 0 ? (
        <p>No early-release or late-start days coming up.</p>
      ) : (
        <table>
          <caption>Upcoming special days</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">School</th>
              <th scope="col">Schedule</th>
              {canEdit && <th scope="col">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.id}>
                <td>{d.service_date}</td>
                <td>{d.school_name}</td>
                <td>{d.schedule_name}</td>
                {canEdit && (
                  <td>
                    <button
                      type="button"
                      disabled={isSaving}
                      onClick={() => void save(() => api.deleteBellCalendarDay(d.id))}
                    >
                      Back to regular: {d.school_name} {d.service_date}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canEdit && (
        <form onSubmit={handleDay}>
          <h4>Mark a special day</h4>
          <label htmlFor="bell-day-date">Date</label>
          <input
            id="bell-day-date"
            type="date"
            value={dayDate}
            onChange={(event) => setDayDate(event.target.value)}
            required
          />
          <label htmlFor="bell-day-name">Schedule to use</label>
          <input
            id="bell-day-name"
            list="bell-day-names"
            maxLength={60}
            value={dayName}
            onChange={(event) => setDayName(event.target.value)}
            required
          />
          <datalist id="bell-day-names">
            {scheduleNames.map((n) => (
              <option key={n} value={n} />
            ))}
          </datalist>
          <label htmlFor="bell-day-scope">Schools</label>
          <select
            id="bell-day-scope"
            value={dayScope}
            onChange={(event) => setDayScope(event.target.value as 'all' | 'school')}
          >
            <option value="all">Every school with a schedule by that name</option>
            <option value="school">Only {bells?.school_name ?? 'the school above'}</option>
          </select>
          <button type="submit" disabled={isSaving}>
            Mark the day
          </button>
        </form>
      )}

      {canEdit && (
        <>
          <h3>Import from a CSV</h3>
          <p>
            A header row of <code>school,schedule,first_bell,dismissal</code>, times as HH:MM
            (24-hour), schools by name. A schedule called Regular is the school&apos;s regular one.
            Check the preview before importing.
          </p>
          <form onSubmit={(event) => void handlePreview(event)}>
            <label htmlFor="bell-import-file">CSV file</label>
            <input
              id="bell-import-file"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => void handleFile(event.target.files?.[0])}
            />
            <label htmlFor="bell-import-text">Or paste it</label>
            <textarea
              id="bell-import-text"
              rows={5}
              value={csv}
              onChange={(event) => {
                setCsv(event.target.value)
                setPreview(null)
              }}
            />
            <button type="submit" disabled={isSaving || csv.trim() === ''}>
              Preview
            </button>
          </form>
          {preview && (
            <>
              <table>
                <caption>{preview.applied ? 'Imported' : 'Preview: nothing saved yet'}</caption>
                <thead>
                  <tr>
                    <th scope="col">Line</th>
                    <th scope="col">School</th>
                    <th scope="col">Schedule</th>
                    <th scope="col">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((r) => (
                    <tr key={r.line}>
                      <td>{r.line}</td>
                      <td>{r.school}</td>
                      <td>{r.schedule}</td>
                      <td>
                        {r.outcome}
                        {r.message ? `: ${r.message}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!preview.applied && preview.rows.some((r) => r.outcome !== 'error') && (
                <button type="button" disabled={isSaving} onClick={handleApply}>
                  Import these bell times
                </button>
              )}
            </>
          )}
        </>
      )}
    </section>
  )
}
