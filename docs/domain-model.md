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
  profile, Phase 6 GIS slice). Consumed by `ors_deadhead_estimator`
  (below) — `DeadheadEstimator` now takes a `Vehicle` argument, and
  the scheduler's pairwise-ordering loop calls it once per (job-pair,
  crew) so each crew's actual dimensions are used, not shared across
  every candidate crew. Deliberately not persisting turning radius (no
  ORS HGV restriction parameter could consume it), wheelchair
  configuration (already modeled via the `qualifications`
  capability-tag system above), vehicle type (no per-vehicle ORS
  profile switching exists), or "applicable road restrictions" (that's
  what height/width/weight restrictions already express at the
  routing-provider level).

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
A pluggable function `(location_a, location_b, vehicle) -> minutes` (widened from a 2-arg
function in the §6 wiring slice — `scheduler.py`'s pairwise-ordering loop now calls it once
per (job-pair, crew), not once per job-pair shared across every candidate crew, so two
different vehicles serving the same pair can get genuinely different numbers). Three
implementations exist:
- `straight_line_deadhead_estimator` (Phase 1): haversine distance /
  average speed, explicitly labeled as an approximation. Used whenever
  no routing API key is configured — the default for CI/tests/local
  dev, and the automatic fallback if a routing API call fails. Ignores
  the `vehicle` argument — distance doesn't depend on it.
- `osrm_deadhead_estimator` (Phase 1, unwired): calls an
  OSRM-compatible routing HTTP API. Written as a scaffold/pattern
  reference but never wired into `services/api` — superseded in
  practice by `ors_deadhead_estimator` below, which the API layer
  actually uses. Also ignores `vehicle` — OSRM's public HTTP API has
  no restriction-parameter mechanism to apply it to, unlike ORS.
- `ors_deadhead_estimator` (Phase 6 GIS slice 1, extended in the §8
  and §6 wiring slices): calls the OpenRouteService Directions API
  (`driving-hgv` profile by default — a real heavy-goods-vehicle
  profile, closer to spec §6's intent than a passenger-car profile).
  `services/api`'s `POST /schedule` wires this in automatically when
  `ISD_API_ORS_API_KEY` is configured (`isd_api.config.settings`),
  falling back to the straight-line estimator (logged at WARNING) if
  the ORS call fails. Accepts `avoid_polygons` (a GeoJSON
  Polygon/MultiPolygon, built by the `avoid_polygons_geojson` helper
  next to it) — the wiring point for spec §8's district-specific
  geographic knowledge: `routers/schedule.py` queries
  `GeographicKnowledgeOverride` rows for the 3 of 8 categories that
  genuinely mean "never route through this point"
  (`FREQUENT_FLOODING`, `UNSAFE_TURN`, `INVALID_TURNAROUND` — see
  "Phase 6 entities" below for why the other 5 are deliberately
  excluded) and passes their locations in. **Now also applies
  per-vehicle restrictions** (spec §6): when the `Vehicle` passed to
  `estimate` has any of `length_m`/`width_m`/`height_m`/`weight_kg`
  set, the request body's `options.profile_params.restrictions` gains
  the corresponding keys (weight converted from persisted kilograms to
  the tons ORS expects). **A real live-verification catch, not
  theoretical**: some published ORS docs describe a required top-level
  `vehicle_type` field alongside `restrictions`; the live API (v2
  directions, checked 2026-09) actively rejects an unrecognized
  `vehicle_type` with a 400, so it's deliberately not sent —
  `restrictions` alone is accepted. §7 (turn/dead-end safety costs)
  and §10 (dynamic rerouting from live incident feeds) still need a
  routing *graph* this system doesn't own and can't customize through
  a simple point-to-point directions call — out of scope here.
  `osrm_deadhead_estimator` has not been exercised against a live
  routing server in this development environment (network-restricted
  sandbox); `ors_deadhead_estimator` **has** — live-verified with a
  real OpenRouteService API key against real Houston-area coordinates,
  for the base estimate, `avoid_polygons` (confirmed a real detour:
  forcing a block on a point actually on the route's returned geometry
  measurably changed the trip duration), and vehicle restrictions
  (confirmed the request shape is accepted without error — the actual
  test route didn't happen to cross a real restricted segment, so no
  observable duration change, but that's a property of the specific
  coordinates chosen, not of the request being malformed). Each still
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
- **`Run.direction`** (added for the ridership decision-support slice
  below): which leg (`am`/`pm`) a run serves — needed to join a run
  against `RidershipOverride` rows at all, since they're keyed by
  direction and `Run` didn't record one before this. Purely an
  API/DB-layer field; the solver's `Job` dataclass has no direction
  concept and doesn't need one (deadhead/scheduling don't depend on
  which leg a run is).
- **Expected-riders decision support** (`GET /runs/{id}/expected-riders`,
  spec §4.3 — see "Not yet implemented" below for the scope boundary):
  not a persisted entity, a read-only computed endpoint resolving each
  student at the run's school via the same override-with-default-
  fallback logic `GET /students/my-family` already uses, then counting
  riders for that run's exact `(service_date, direction)`. Flags
  `ambiguous=true` when more than one `Run` shares the same
  `(school_id, service_date, direction)` — this system has no
  student-to-specific-run assignment, so the count can't be correctly
  attributed to just one of several runs serving the same school/leg
  that day. `PATCH /runs/{id}` (passenger_count only) lets a dispatcher
  apply the computed count manually; nothing applies it automatically
  (spec §21: decision support, not autonomous authority — same
  precedent as Phase 6's substitute-candidate ranking).

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
  precedent as `DriverAbsence`. Three more nullable field groups, each
  required together and only meaningful for one specific category
  (enforced in `routers/geographic_knowledge.py`'s
  `_validate_category_specific_fields`, not a schema-level validator):
  `window_start_minute`/`window_end_minute` (minute-of-day range, for
  `CONGESTION_WINDOW`), `restricted_dimension`/`max_allowed_value`
  (one of `Vehicle`'s own `length_m`/`width_m`/`height_m`/`weight_kg`
  field names plus a threshold, for `VEHICLE_SIZE_RESTRICTED`), and
  `school_id` (nullable FK to `School`, for `PREFERRED_ENTRANCE`).

  **7 of the 8 categories are now applied to routing**, each via a
  mechanism appropriate to what it actually means:
  `FREQUENT_FLOODING`/`UNSAFE_TURN`/`INVALID_TURNAROUND` are always-on
  for the whole solve (`routers/schedule.py`'s `_HARD_AVOID_CATEGORIES`
  → ORS `avoid_polygons`, `isd_solver.domain.avoid_polygons_geojson`).
  `DIFFICULT_INTERSECTION` is included in that same always-on set — a
  deliberate, named compromise rather than a free win: the category
  name implies a caution/cost ("drive carefully here"), not a block,
  but ORS's directions API has no soft-cost lever to express that
  distinction, so it's applied as a full avoid-zone, a real behavior
  change from what the name implies.
  `CONGESTION_WINDOW` is applied per-solve, not per-leg
  (`_congestion_avoid_points`): a zone is included only when at least
  one run actually being scheduled that day has a required window
  overlapping it — a deliberate, named precision tradeoff (the exact
  deadhead-leg travel time is a CP-SAT decision variable, not known
  until after solving, so it can't gate inclusion the way a run's own
  already-known window can) rather than threading a time parameter
  through `DeadheadEstimator` and every `scheduler.py` call site.
  `VEHICLE_SIZE_RESTRICTED` is applied per-vehicle, per-call
  (`_size_restrictions_for_schedule` → `isd_solver.domain.
  SizeRestriction`, re-evaluated by `ors_deadhead_estimator` against
  the specific `Vehicle` passed to `estimate` on every call) — a small
  vehicle that fits under a restricted bridge never detours around it,
  only an oversized one does; an unknown vehicle dimension is never
  treated as an assumed violation (spec §21: don't guess).
  `PREFERRED_ENTRANCE` doesn't touch `avoid_polygons` at all — instead
  `_preferred_entrance_locations` substitutes this override's own
  point for that `school_id`'s runs' job location, in place of the
  school's own `location_lat`/`location_lon`, inside `_to_solver_inputs`
  (a run's destination becomes the actual gate/entrance, not the
  school's abstract centroid). If more than one `PREFERRED_ENTRANCE`
  override exists for the same school, that school is left out
  entirely (spec §21: don't guess which one applies) and its runs fall
  back to the school's own centroid. Field trips use
  `DestinationProfile.approved_entrance` instead (free text, not
  coordinates) since they're never solved by CP-SAT.

  Only `OTHER` remains excluded, structurally rather than
  provisionally: it exists specifically as the catch-all for knowledge
  that doesn't fit any of the other 7 categories, so by construction
  it has no defined behavior a routing engine could apply.
- **VehiclePosition** (spec §9/§18, ADR 0009): the latest known GPS
  position for a crew's vehicle — `crew_id` (unique: one row per crew,
  overwritten in place), lat/lon, `recorded_at`. Reported by the
  driver's own tablet (`PUT /drivers/{id}/position`, browser
  Geolocation API — no dedicated GPS/AVL hardware, per ADR 0009) while
  a run is in progress; read via `GET /schedule/{date}/fleet-positions`
  (dispatcher's spec §17 "GPS fleet view") or
  `GET /students/{id}/bus-position` (a family's spec §18 "approximate
  bus location" for one child's leg — `available`/`ambiguous`-shaped
  like `ExpectedRidersRead`, never guessing which bus when more than
  one run serves the same school/date/direction). MVP scope
  deliberately stores only the latest position, not a breadcrumb
  trail — see ADR 0009 for why.
- **FieldTrip** (spec §12): a trip record — `requesting_party`/
  `origin`/`destination` (free text), an optional `destination_profile_id`
  linking to a reusable `DestinationProfile` (spec §12.3, below),
  `departure_at`/`expected_return_at` (multi-day/overnight trips are
  supported — conflict-checking splits a trip's span into one
  per-calendar-day window, see `routers/field_trips.py`'s
  `_daily_windows`), `actual_return_at`, `passenger_count`,
  `assigned_driver_id`/`assigned_vehicle_id` (direct FKs, not a `Crew`
  pairing — spec §11's "Daily Operational Assignment" isn't built as
  its own abstraction, and a trip doesn't need a day-long crew row),
  `bus_assistant_name` (free text, no second staff entity),
  `trip_contact`, `special_instructions`, `status` (spec §12's 7-value
  lifecycle), and `required_qualifications` (shared for both "vehicle
  requirements" and "accessibility requirements" — this system already
  expresses both through `Qualification`, e.g. a wheelchair-lift tag).
  **Not run through the CP-SAT solver** — assigning a driver/vehicle
  is a manual dispatcher action (spec §21), same shape as Phase 6's
  substitute-coverage ranking. `GET /field-trips/{id}/conflicts` (spec
  §12.1) checks overlapping regular-route `Assignment`s and other
  `FieldTrip`s for a proposed driver/vehicle — training, maintenance,
  and required-break conflicts are named in the spec but have no
  corresponding entity in this schema, so they're not checked (not a
  missed case — nothing exists to check against). Spec §12.2's "delay
  management" is not a separate mechanism: re-calling the conflicts
  endpoint after a `PATCH` to `expected_return_at` *is* the
  reevaluation. `services/web`'s `/field-trips` page (PR #26) closed
  out the UI half of this slice.
- **DestinationProfile** (spec §12.3): reusable transportation-specific
  information for a frequently used field-trip destination — name,
  optional lat/lon, approved entrance, parking notes, turn
  restrictions, driver notes. Its own entity a `FieldTrip` optionally
  links to (`destination_profile_id`), not fields bolted onto
  `FieldTrip` itself — the whole point is reuse across many trips to
  the same place. Nothing auto-matches a trip's free-text `destination`
  to a profile; the dispatcher picks one explicitly when creating or
  editing a trip.
- **Field-trip observed duration** (spec §20, `GET /field-trips/observed-duration?destination=`
  or `?destination_profile_id=`): the same historical-learning idea as
  `GET /runs/observed-duration`, but a completed `FieldTrip` already
  stores its own actual start/end directly (`departure_at`,
  `actual_return_at`) — no audit-log lookup needed, since that data was
  never split across separate status-change events the way a regular
  `Assignment`'s was. Decision support only: `FieldTripsPage`'s "Add
  field trip" form shows the computed average/most-recent for a
  dispatcher to read and use to suggest `expected_return_at`; nothing
  writes to a trip automatically.
- **Observed run duration** (spec §20, `GET /runs/observed-duration`):
  historical learning applied to `Run.duration_minutes` — spec §20's
  own worked example ("a route consistently requires 48 minutes
  despite an initial estimate of 40"). Computed entirely from data
  this system already persists, no new table: a completed
  `Assignment`'s actual start/end are read straight off its own
  `status_changed` audit entries (spec §14) rather than a new
  breadcrumb/history column. Runs have no recurring-route identity
  (the never-built `Route`/template table, above), so "this route" is
  approximated as every completed run sharing a `(school_id,
  direction)` pair across any `service_date`. Decision support only
  (spec §21) — `SchedulePage`'s "Add run" form shows the computed
  average/most-recent for a dispatcher to read and manually copy into
  `duration_minutes`; nothing writes to it automatically.
- **Announcement** (spec §9/§18): a dispatcher-authored notice for
  drivers and/or families — `message` (free text), `category`
  (general/delay/substitution/route_change — informational label
  only), `audience` (all/family/driver), `school_id` (nullable FK to
  `School` — null means district-wide; meaningless for
  `audience=driver`, which ignores it). Covers spec §9's "Messages
  from dispatch" and §18's "Transportation announcements"/"Delay
  notifications"/"Bus substitution notices"/"Route-change notices" —
  **almost always human-authored, with one narrow, principled
  exception**: when a crew's driver/vehicle genuinely changes on an
  already-solved day (spec §13) and the affected school+date+direction
  is unambiguous (exactly one `Run` matches — spec §21's "never guess"
  decision-support rule, same precedent as expected-riders and
  `GET /students/{id}/bus-position`), the system auto-generates a
  school-scoped family notice — see
  `routers/announcements._maybe_create_substitution_announcement`,
  wired from both `PATCH /crews/{id}` and
  `PATCH /schedule/assignments/{id}`. When more than one run shares
  that school/date/direction, no notice is generated rather than
  guessing which families are actually affected. Every other
  category/audience combination is still exclusively dispatcher-
  authored via `POST /announcements` — this system has no
  ETA-calculation engine to auto-detect a delay, for example.
- **DriverReport** (spec §9): the driver app's "Incident reporting" and
  "Vehicle defect reporting" — one entity with a `report_type`
  discriminator (`incident`/`vehicle_defect`) rather than two nearly
  identical entities. `vehicle_id` is deliberately not driver-supplied:
  the router resolves it from the driver's own `Crew` for
  `service_date` (the vehicle they were actually driving that day), so
  the driver-app form only ever needs a type and a description (spec
  §9: "minimal typing"). Nullable when the driver has no crew that
  date, or the incident doesn't involve a specific vehicle.

## Not yet implemented (later phases, listed so Phase 1 doesn't silently drop them)

- Automated bus-stop generation from walking-distance/road-safety constraints (spec §3.1) — Phase 6, needs GIS/road-network data (PostGIS is deferred, ADR 0006)
- Spec §4.3's actual behavior — stop-sequence route shortening ("if all riders at a stop don't ride, remove that stop, recalculate sequence/ETAs") — needs a `Route`/stop-sequence model this system has never built (ADR 0001 named the intent, never built). What *is* done: `GET /runs/{id}/expected-riders` computes a real rider count from `Student`/`RidershipOverride` as decision support for `Run.passenger_count` (see "Phase 6 entities" above) — closer to reality than the fully-manual guess it replaced, but not the stop-shortening optimization spec §4.3 describes
- Ridership reporting cutoff / route-lock configuration (spec §4.4)
- A recurring `route` (template) table distinct from dated `run` instances — ADR 0001 named this intention for Phase 2+, never built; Phase 5 worked around its absence rather than building it (see RidershipOverride above). Observed-run-duration (§20, above) approximates route identity via (school_id, direction) instead of a real template — good enough for learning, not a substitute for the real table
- Field trips (spec §12) is done end-to-end (`FieldTrip` + `/field-trips` UI, overnight trips, `DestinationProfile` §12.3, and observed-duration §20, above) — not yet: conflict-checking against training/maintenance (no such entity exists — a genuine gap, not an oversight)
- Spec §6 is now done to the extent an external point-to-point routing API can express it: real road-network travel time, per-vehicle length/width/height/weight restrictions, and district-specific avoid-zones (§8) are all applied via `ors_deadhead_estimator`. Turn/dead-end safety costs (§7) and dynamic rerouting (§10) remain genuinely out of scope — both need a routing *graph* this system doesn't own, not just a point-to-point directions call, a different technical approach than anything built so far.
- District-specific geographic knowledge / local roadway overrides (spec §8) — persistence done, and 7 of 8 categories now applied to routing: flooding/difficult-intersection/unsafe-turn/invalid-turnaround via always-on ORS `avoid_polygons`, congestion-window per-solve when a run's window overlaps it, vehicle-size-restriction per-vehicle via `isd_solver.SizeRestriction`, preferred-entrance by substituting a run's job location with the override's own point (`GeographicKnowledgeOverride`, above). Only `other` remains excluded, structurally rather than provisionally — it's the catch-all for knowledge that doesn't fit any other category, so by construction it has no defined routing behavior
- Dynamic rerouting around road closures/incidents (spec §10) — Phase 6, same GIS dependency
- Live GPS bus location (spec §9/§18) is done for position itself (`VehiclePosition`, ADR 0009, above) — dispatcher fleet view and per-child "locate bus." Delay/substitution/route-change/general notifications (spec §18) and "messages from dispatch" (spec §9) are now done too (`Announcement`, above), with per-school scoping and one narrow auto-generated exception (a genuine, unambiguous driver/vehicle substitution) — every other notification is still exclusively dispatcher-authored, since this system has no ETA engine or general event-to-notification pipeline. Incident reporting / vehicle defect reporting (spec §9) is now done too (`DriverReport`, above). Still unbuilt: turn-by-turn navigation (spec §9 — deliberately deferred alongside §7/§10, since it needs the same routing graph this system doesn't own)
- Historical operational data / learning-adjusted estimates (spec §20) — duration learning for `Run.duration_minutes` is done (`GET /runs/observed-duration`, above). Not yet: traffic-delay and route-deviation tracking (both need a planned route geometry and live position history this system doesn't have — ADR 0009 deliberately keeps only the latest GPS position, no breadcrumb trail) and field-trip duration learning (though `FieldTrip.actual_return_at` already captures the raw data needed, no aggregation endpoint exists for it yet, unlike regular runs)
