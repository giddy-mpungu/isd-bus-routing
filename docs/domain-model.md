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
- `length_m`, `width_m`, `height_m`, `weight_kg` (spec §6's vehicle
  profile, Phase 6 GIS slice — persisted only. `DeadheadEstimator`
  (below) is still `Callable[[Location, Location], int]`, with no
  `Vehicle` argument, so nothing in the scheduler reads these yet —
  see the "DeadheadEstimator" section for exactly what's deferred and
  why). Deliberately not persisting turning radius (no ORS HGV
  restriction parameter could consume it), wheelchair configuration
  (already modeled via the `qualifications` capability-tag system
  above), vehicle type (no per-vehicle ORS profile switching exists),
  or "applicable road restrictions" (that's what height/width/weight
  restrictions already express at the routing-provider level).

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
A pluggable function `(location_a, location_b) -> minutes`. Three
implementations exist:
- `straight_line_deadhead_estimator` (Phase 1): haversine distance /
  average speed, explicitly labeled as an approximation. Used whenever
  no routing API key is configured — the default for CI/tests/local
  dev, and the automatic fallback if a routing API call fails.
- `osrm_deadhead_estimator` (Phase 1, unwired): calls an
  OSRM-compatible routing HTTP API. Written as a scaffold/pattern
  reference but never wired into `services/api` — superseded in
  practice by `ors_deadhead_estimator` below, which the API layer
  actually uses.
- `ors_deadhead_estimator` (Phase 6 GIS slice 1, extended in the §8
  wiring slice): calls the OpenRouteService Directions API
  (`driving-hgv` profile by default — a real heavy-goods-vehicle
  profile, closer to spec §6's intent than a passenger-car profile).
  `services/api`'s `POST /schedule` wires this in automatically when
  `ISD_API_ORS_API_KEY` is configured (`isd_api.config.settings`),
  falling back to the straight-line estimator (logged at WARNING) if
  the ORS call fails. Also accepts `avoid_polygons` (a GeoJSON
  Polygon/MultiPolygon, built by the `avoid_polygons_geojson` helper
  next to it) — the wiring point for spec §8's district-specific
  geographic knowledge: `routers/schedule.py` queries
  `GeographicKnowledgeOverride` rows for the 3 of 8 categories that
  genuinely mean "never route through this point"
  (`FREQUENT_FLOODING`, `UNSAFE_TURN`, `INVALID_TURNAROUND` — see
  "Phase 6 entities" below for why the other 5 are deliberately
  excluded) and passes their locations in. **Still not full bus-legal
  routing per spec §6** — every crew gets the same `driving-hgv`
  default regardless of its actual vehicle's dimensions; applying
  per-vehicle height/width/weight/length restrictions would require
  widening `DeadheadEstimator`'s signature to also take a `Vehicle`,
  which ripples into every `scheduler.py` call site — a deliberate
  follow-up, not part of this estimator. §7 (turn/dead-end safety
  costs) and §10 (dynamic rerouting from live incident feeds) need a
  routing *graph* this system doesn't own and can't customize through
  a simple point-to-point directions call — out of scope here too.
  `osrm_deadhead_estimator` has not been exercised against a live
  routing server in this development environment (network-restricted
  sandbox); `ors_deadhead_estimator` **has** — live-verified with a
  real OpenRouteService API key against real Houston-area coordinates,
  both for the base estimate and for `avoid_polygons` (confirmed a
  real detour: forcing a block on a point actually on the route's
  returned geometry measurably changed the trip duration). Each still
  takes its HTTP call as a dependency-injected parameter so it can be
  unit-tested without live network access in CI.

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
  Completing a substitution uses `PATCH /crews/{id}` (repoints an
  existing crew's driver — needed because a `Crew` row isn't freed
  just by marking its driver absent, see REBOOT.md's gotcha #9) when
  the candidate has no crew of their own that date, or the existing
  `PATCH /schedule/assignments/{id}` when they do — never
  `POST /crews`, which 409s on the vehicle's own uniqueness
  constraint. Spec §21: decision support, not an autonomous authority.
- **GeographicKnowledgeOverride** (spec §8, GIS slice 2): a point
  location, a `category` (frequent flooding, difficult intersection,
  unsafe turn, invalid turnaround, congestion window, vehicle-size
  restriction, preferred entrance, other), and a required free-text
  `note` — the one piece of routing-relevant data this system owns
  itself, per ADR 0007. `note` is deliberately free text, unlike
  `DriverAbsence`'s avoidance of it (PII risk) — the whole point of
  this entity is staff-authored institutional knowledge a category
  alone can't carry. `POST`/`GET /geographic-knowledge`, both
  transportation_admin and dispatcher (day-to-day operational
  knowledge, same RBAC shape as `DriverAbsence`, broader than
  `Stop`'s admin-only creation). Who added it is the audit log, same
  precedent as `DriverAbsence`. **Now partially applied to routing**
  (the §8 wiring slice): `routers/schedule.py`'s `_HARD_AVOID_CATEGORIES`
  turns `FREQUENT_FLOODING`/`UNSAFE_TURN`/`INVALID_TURNAROUND` overrides
  into ORS `avoid_polygons` (`isd_solver.domain.avoid_polygons_geojson`)
  on every `POST /schedule` when an ORS key is configured. The other 5
  categories are deliberately excluded, not just not-yet-built:
  `DIFFICULT_INTERSECTION` is a caution/cost, not a hard block;
  `CONGESTION_WINDOW` is time-of-day dependent and the estimator has
  no time parameter; `VEHICLE_SIZE_RESTRICTED` depends on which
  vehicle (ties to the still-deferred per-vehicle-restrictions
  follow-up); `PREFERRED_ENTRANCE` is a positive preference, the
  opposite of an avoidance, needing a different mechanism entirely;
  `OTHER` is too ambiguous to apply an unpredictable effect for.

## Not yet implemented (later phases, listed so Phase 1 doesn't silently drop them)

- Automated bus-stop generation from walking-distance/road-safety constraints (spec §3.1) — Phase 6, needs GIS/road-network data (PostGIS is deferred, ADR 0006)
- Wiring ridership declarations into the solver (dropping empty stops, recalculating ETAs, spec §4.3) — `Run.passenger_count` is still a static admin-entered int; a natural follow-up to the Phase 5 MVP, not part of it
- Ridership reporting cutoff / route-lock configuration (spec §4.4)
- A recurring `route` (template) table distinct from dated `run` instances — ADR 0001 named this intention for Phase 2+, never built; Phase 5 worked around its absence rather than building it (see RidershipOverride above)
- Field trips / Trip conflict detection (spec §12) — Phase 6
- Full bus-legal routing per spec §6/7 — `ors_deadhead_estimator` (Phase 6 GIS slice 1) gets real road-network travel time on a heavy-vehicle profile, and `Vehicle` now persists length/width/height/weight (Phase 6 GIS slice, above), but the two still aren't connected: `DeadheadEstimator`'s signature doesn't take a `Vehicle` yet, so every crew still gets the same undifferentiated `driving-hgv` profile. Turn/dead-end safety costs (§7) need a routing graph/profile this system doesn't own, not just a point-to-point directions call — out of scope regardless.
- District-specific geographic knowledge / local roadway overrides (spec §8) — persistence done, and 3 of 8 categories now applied to routing via ORS `avoid_polygons` (`GeographicKnowledgeOverride`, above); the other 5 categories (caution/time-dependent/vehicle-dependent/preference/ambiguous) each need a different mechanism than a hard avoid-zone, not just more plumbing
- Dynamic rerouting around road closures/incidents (spec §10) — Phase 6, same GIS dependency
- Live GPS bus location, delay/substitution/route-change notifications (spec §18) — Phase 6+, no live-tracking or notification infrastructure exists yet
- Historical operational data / learning-adjusted estimates (spec §20) — Phase 6
