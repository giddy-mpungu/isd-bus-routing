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
  claim about what any specific driver-hour law requires.**

### Crew
- `id`
- `driver_id`, `vehicle_id`
- `available_window`: `TimeWindow` the crew is available to work today

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

## Not yet implemented (later phases, listed so Phase 1 doesn't silently drop them)

- Student, Stop entities and student-to-stop/route assignment (spec §3) — Phase 2+
- Field trips / Trip conflict detection (spec §12) — Phase 2/6
- Driver absence and substitute ranking (spec §13) — Phase 6
- Ridership-status-driven dynamic stop removal (spec §4) — Phase 5/6
- Bus-legal road-network routing and turn penalties (spec §6/7) — Phase 6, requires a routing graph/profile aware of bus dimensions and restrictions, not either estimator above
