# Domain model

Terminology defined in ADR 0001. This document defines the entities
implemented in `services/solver/src/isd_solver/domain.py` for Phase 1.
Fields not needed until later phases are noted but not yet implemented,
to keep Phase 1 small and testable.

## Phase 1 entities (implemented)

### School
- `id`
- `name`
- `bell_windows`: list of `TimeWindow` (an arrival or dismissal window
  the run must satisfy) — a school may have more than one (e.g. AM
  arrival and PM dismissal are separate windows, spec §5).
- `location`: `(lat, lon)`

### TimeWindow
- `earliest`, `latest`: the window a Job must arrive/depart within
  (spec §2.1: "cannot arrive at a school within the required time
  window" is a hard constraint).

### Job
Represents one Run-instance to be scheduled (spec §5's per-school
route window). Trips (spec §12) will extend this in a later phase.
- `id`
- `school_id`
- `window`: `TimeWindow` — required arrival window
- `duration_minutes`: estimated time to complete the run itself
  (loading + driving), *not* including buffer
- `buffer_minutes`: operational buffer required around this job (spec
  §16) — configured per district/job, never assumed
- `location`: `(lat, lon)` — used to estimate deadhead travel to/from
  other jobs
- `required_vehicle_qualifications`: e.g. wheelchair-accessible (spec
  §15) — set, may be empty
- `passenger_count`: expected riders for this job. Defaults to 0,
  meaning "ridership not modeled" — a 0-passenger job never triggers a
  capacity constraint. A vehicle with unknown capacity (`allowable_capacity()
  is None`) fails closed against any job with `passenger_count > 0` —
  unknown capacity is never treated as unlimited capacity.

### Vehicle
- `id`
- `qualifications`: set of capability tags (e.g. `"wheelchair"`)
- `nominal_capacity`, `effective_capacity` (spec §15 distinguishes
  these; either or both may be `None` if unknown). `allowable_capacity()`
  returns effective if known, else nominal, else `None`.

### Driver
- `id`
- `license_qualifications`: set, e.g. `{"CDL_A"}`, `{"CDL_B"}`,
  `{"NON_CDL_C"}` (spec §1, §15)
- `max_continuous_minutes`: district-configured limit on continuous
  driving/duty time before a break is required. **This is a
  configuration value the district supplies — this codebase makes no
  claim about what any specific driver-hour law requires.** Enforced
  by the scheduler as a hard constraint (`scheduler.py`): a crew's
  driver never has a duty span (first assigned job's start to last
  assigned job's end) exceeding this limit. Phase 1 approximation: the
  whole span counts as one continuous duty period — a gap between two
  jobs isn't yet recognized as a qualifying break that would reset the
  limit. Real break-aware modeling is a future enhancement.

### Crew
- `id`
- `driver_id`, `vehicle_id`
- `available_window`: `TimeWindow` the crew is available to work today
- `busy_intervals`: time ranges within `available_window` this crew is
  already committed elsewhere (spec §21: a locked assignment protects
  that specific commitment, not the crew's whole day). Populated by
  `routers/schedule.py` from the crew's other locked assignments on a
  re-solve — a crew is no longer excluded outright just because it has
  one locked assignment. No deadhead buffer is enforced around a busy
  interval, since there's no `Job`/location for whatever's occupying
  it — a time-only exclusion, not a full scheduling constraint like
  the pairwise job-vs-job case.

### DeadheadEstimator
A pluggable function `(location_a, location_b) -> minutes`. Two
implementations ship in Phase 1:
- `straight_line_deadhead_estimator`: haversine distance / average
  speed, explicitly labeled as an approximation.
- `osrm_deadhead_estimator`: calls an OSRM-compatible routing HTTP API
  for a real road-network travel-time estimate. This is still **not**
  the bus-legal routing spec §6 requires — it uses a passenger-car
  driving profile, with no height/weight/turning-radius/road-restriction
  awareness. It has not been exercised against a live routing server in
  this development environment (network-restricted sandbox); its
  `http_get` parameter is dependency-injected specifically so it can be
  unit-tested without live network access, and it should be validated
  against a real endpoint before any operational use. A true bus-legal
  routing profile remains a Phase 6 integration point.

### Assignment / SchedulingResult / Explanation
See `scheduler.py` and `explain.py` docstrings — these are the solver
*outputs*, not inputs, so they're defined next to the code that
produces them rather than duplicated here.

## Phase 5 entities (`services/api/src/isd_api/models.py`, persistence only — not part of the solver domain)

- **Stop**: a manually-created boarding/alighting location (spec §3).
  `label`, `location_lat`/`location_lon`. No automated stop-generation
  yet — see "Not yet implemented" below.
- **Student**: `full_name`, `school_id`, optional `stop_id`,
  `default_ridership` (spec §4.1: `rides` or `does_not_ride`).
  Deliberately minimal — no address/geocoding field, since nothing
  consumes it yet (same PII-minimalism precedent as `Driver`).
- **student_guardians**: many-to-many join between `Student` and
  `User` (a parent's access to their children, spec §17) — distinct
  from `User.student_id`, which is a student's *own* login.
- **RidershipOverride**: a per-day, per-leg (`direction`: `am`/`pm`)
  override of a student's default ridership (spec §4.2), keyed by
  `(student_id, service_date, direction)`. Deliberately keyed by date
  rather than a specific `Run` row — `Run` rows are per-service-date
  (no recurring `Route` template table exists, despite ADR 0001 having
  named that intention — see "Not yet implemented" below), so a
  student's standing assignment can't point at one without needing
  re-linking every day. Also spec §4.5's "late request to ride" — same
  mechanism, no separate code path.

## Phase 6 entities (`services/api/src/isd_api/models.py`, first slice — spec §13 only)

- **DriverAbsence**: `driver_id`, `service_date`, `start_minute`/
  `end_minute` (0/1439 for a whole-day absence — spec §13's "Partial-day
  absence" reason is representable this way, so it's deliberately not
  a separate `AbsenceReason` value), `reason` (spec §13's enumerated
  list, minus any free-text medical detail — "should store only the
  information necessary for transportation operations"). Who reported
  it is captured by the existing audit log, not a column here.
- **Substitute-candidate ranking** (spec §13.1) is *not* a persisted
  entity — it's a read-only, computed endpoint
  (`GET /drivers/{id}/substitute-candidates`) over existing data
  (`Assignment`/`Crew`/`Driver`). See `routers/absences.py`'s
  `_rank_substitute_candidates` docstring for the scoring factors and
  why a driver-license-vs-vehicle-type qualification check was
  deliberately left out (no such compatibility mapping exists
  anywhere in this schema — would have been a fabricated signal).
  Completing a substitution reuses the existing `POST /crews` +
  `PATCH /schedule/assignments/{id}` endpoints, not a new one — spec
  §21: decision support, not an autonomous authority.

## Not yet implemented (later phases, listed so Phase 1 doesn't silently drop them)

- Automated bus-stop generation from walking-distance/road-safety constraints (spec §3.1) — Phase 6, needs GIS/road-network data (PostGIS is deferred, ADR 0006)
- Wiring ridership declarations into the solver (dropping empty stops, recalculating ETAs, spec §4.3) — `Run.passenger_count` is still a static admin-entered int; a natural follow-up to the Phase 5 MVP, not part of it
- Ridership reporting cutoff / route-lock configuration (spec §4.4)
- A recurring `route` (template) table distinct from dated `run` instances — ADR 0001 named this intention for Phase 2+, never built; Phase 5 worked around its absence rather than building it (see RidershipOverride above)
- Field trips / Trip conflict detection (spec §12) — Phase 6
- A dispatcher-facing UI for absence reporting/substitute ranking (spec §13 backend is done — see "Phase 6 entities" above; no `services/web` page yet, an intentional, named follow-up)
- Bus-legal road-network routing and turn penalties (spec §6/7) — Phase 6, requires a routing graph/profile aware of bus dimensions and restrictions, not either estimator above
- District-specific geographic knowledge / local roadway overrides (spec §8) — Phase 6, depends on §6/7's routing graph existing first
- Dynamic rerouting around road closures/incidents (spec §10) — Phase 6, same GIS dependency
- Live GPS bus location, delay/substitution/route-change notifications (spec §18) — Phase 6+, no live-tracking or notification infrastructure exists yet
- Historical operational data / learning-adjusted estimates (spec §20) — Phase 6
