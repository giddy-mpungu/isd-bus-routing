# REBOOT.md — Session Continuity Script

Machine-readable state snapshot for isd-bus-routing. **Read this first**
when resuming work in a new session/branch after a context reset. Not
user-facing documentation — see README.md and docs/architecture.md for
that. Update this file after every merged increment (committed directly
to `main`, not through the branch→PR→CI cycle used for everything else —
this is a living operational document, not a feature).

## Identity / non-negotiable conventions

- Sole author/dev: Gideon Mpungu (gmbugampungu@gmail.com). **Every**
  commit authored as "Gideon Mpungu". Never add other
  contributors/co-authors.
- Git: **local** (repo-scoped, not `--global`) `user.name="Gideon Mpungu"`
  already set on this checkout. GitHub account: `giddy-mpungu`. Repo:
  https://github.com/giddy-mpungu/isd-bus-routing (private).
- Workflow: one branch per feature → PR via `gh` CLI → CI must pass →
  `gh pr merge --merge --delete-branch` → sync local `main`. Followed
  for every PR this session (11 so far) with two accidental exceptions
  where a commit was made directly on `main` before remembering to
  branch first (caught before pushing both times — fixed by
  `git branch <name>` at the current commit, `git reset --hard
  origin/main`, then `git checkout <name>` and pushing that instead;
  safe only because `origin/main` was confirmed to be a strict
  ancestor of local `main` first). **Always run `git checkout -b
  <branch>` as the literal first step of any new increment**, before
  writing any file.
- `gh` CLI path on this Windows machine (not on default bash PATH):
  `"/c/Program Files/GitHub CLI/gh.exe"`.
- Node.js path (not on default bash PATH): `export PATH="/c/Program Files/nodejs:$PATH"` before any `npm`/`node` call in the Bash tool.
- Standing instructions from the user (persistent memory, apply always):
  - Security-by-design by default, not only when asked. When security
    and a stated UX requirement conflict, hold the UX requirement
    fixed and find the *most secure option that still satisfies it* —
    don't unilaterally pick one over the other, and say so explicitly.
  - Give explicit, numbered, shell-correct (confirm bash vs
    PowerShell) step-by-step instructions when handing the user
    commands to run themselves.
  - End every turn/session by stating the concrete next step and what
    it achieves.
  - As of 2026-08-28: work continuously, no pausing for check-ins,
    until the project is done or the user says stop.
  - Always read this file and persistent memory at the start of every
    session/context reset — confirmed standing practice, not
    optional, not just something to write to.

## Architecture (condensed — full reasoning in docs/adr/0001–0007)

Monorepo, 3 services, each separately installed:

- **services/solver** — Python + OR-Tools CP-SAT. Pure in-memory
  scheduling engine, no DB/HTTP/auth. Multi-school crew scheduling
  (spec §5).
- **services/api** — Python + FastAPI + SQLAlchemy 2.0 + Alembic. Owns
  persistence, RBAC, audit. Calls solver **in-process** (library call,
  not network).
- **services/web** — React 19 + TypeScript + Vite. Dispatcher console.
  oxlint (not ESLint) + Prettier. Vitest + React Testing Library.

**Gotchas that will bite again if forgotten:**

1. `services/api` imports `isd_solver` directly but does **not**
   declare it as a pyproject dependency (no portable monorepo
   path-dependency solution exists for pip). **Solver must always be
   installed before api** — README, CI (`ci.yml`'s `api` job runs
   `pip install -e ../solver` first), and any local setup. Broke CI
   once already (PR #7) when forgotten.
2. mypy + numpy: `ortools` pulls in `numpy` transitively. A newer
   numpy can ship `.pyi` stubs using Python-3.12-only syntax that
   breaks mypy under this project's `python_version="3.11"` target —
   a **parse-time** error. Per-module `ignore_errors`/
   `follow_imports="skip"` targeted at `numpy`/`numpy.*` does **not**
   suppress it (verified empirically, twice). Working fix: solver uses
   a **global** `follow_imports="skip"` in `[tool.mypy]` (safe —
   `packages=["isd_solver"]` exempts its own code from it); api uses a
   **targeted override on `ortools`/`ortools.*`** (not numpy) with
   `follow_imports="skip"`, cutting the chain before numpy while still
   fully type-checking `isd_solver`'s real API (verified both
   directions with deliberate-error sanity tests). If this resurfaces
   on a future dependency bump, apply the same pattern.
3. Windows: `core.autocrlf=true` (Git for Windows default) + no
   `.gitattributes` (fixed now, PR #7) meant local files checked out
   CRLF while the repo stores LF, which made `prettier --check` fail
   on every file locally (not in CI, which runs on Linux). If a wall
   of prettier failures appears that doesn't match reality, check
   `.gitattributes` survived and `git config core.autocrlf`.
4. Docker: a named volume's mount point is created **owned by root**
   by default — if the container drops to a non-root `USER` before any
   volume is attached (as `services/api/Dockerfile` does), writes to
   that mount fail. Fix applied: `mkdir -p /data && chown -R appuser
   /data` *before* `USER appuser`. If a future volume mount is added,
   apply the same pattern.
5. docker-compose: `VAR: ${VAR:-default}` syntax **always sets** the
   env var in the container (to `default`, or `""` if `default` is
   empty) — it does not mean "leave unset so the app's own fallback
   applies." Setting `ISD_API_JWT_SECRET_KEY: ${ISD_API_JWT_SECRET_KEY:-}`
   passed a genuinely empty string into the container, which
   pydantic-settings read as a real (invalid) value instead of falling
   back to its own default — broke login with a 500
   ("HMAC key must not be empty"). Fix: don't list a compose env var
   at all when the intent is "let the app's own default apply."
6. **Windows: a `uvicorn` dev server started via the Bash tool can
   become an unkillable "ghost"** — `netstat -ano`/PowerShell's
   `Get-NetTCPConnection` both still report it LISTENING on its port,
   but `taskkill //PID <pid>` reports success without actually freeing
   the port, and `Get-CimInstance Win32_Process`/`Get-Process` (native
   Windows, PowerShell tool) can't find that PID *or any python.exe at
   all* — the process is apparently invisible to native Win32 process
   enumeration from this environment, likely a sandbox/namespace
   artifact of how the Bash tool's background processes are hosted.
   Happened once already (Phase 4 → auth-hardening session boundary).
   **Don't burn time hunting the PID down** — just start the next dev
   server on a different port (e.g. 8001) and a different SQLite file
   (e.g. `verify_dev.db` instead of `isd_api_dev.db`, which the ghost
   process may also still hold open, causing `rm`/`del` to fail with
   "Device or resource busy") for that verification pass instead. This
   worked cleanly a second time for Phase 5's manual verification
   (`phase5_verify.db` + port 8001) — the same ghost PID from the
   Phase 4 → auth-hardening boundary was *still* squatting on port
   8000 at the start of the Phase 5 session, confirming this isn't a
   one-off: expect it, don't re-diagnose it each time.
7. **A new nullable FK on `User` (or any model) must be wired in
   *three* places, not two** — the SQLAlchemy column, the Pydantic
   schema, **and** the router's ORM constructor call that actually
   builds the object from the schema. Added `User.student_id` (Phase
   5) and `UserCreate.student_id`/`UserRead.student_id` correctly, but
   `routers/users.py`'s `create_user()` builds `User(...)` with an
   explicit kwarg list (`email=`, `driver_id=`, `school_id=`, ...) —
   forgetting to add `student_id=payload.student_id` there meant the
   field was accepted by the API, validated, echoed as `null` in the
   response, and silently discarded. Compiled fine, all existing tests
   passed (nothing exercised the new field), only caught by manually
   creating a student login and checking the response body. If a
   future field addition to `User` (or similar) doesn't show up where
   expected, check the router's constructor call first, not just the
   model/schema.
8. **Same-school, same-day test fixtures with non-overlapping run
   windows are a solver-tie trap** — if two runs at the same school
   don't overlap in time, `solve_multi_school_schedule`'s
   minimize-crews-used objective is free to combine them onto *one*
   crew rather than using both crews created for them, leaving the
   "other" crew (and driver) with zero assignments that day. A test
   fixture built assuming "driver B is busy today because I gave them
   a crew and a run" can silently be wrong — the solver may have
   quietly reassigned driver B's run onto driver A's crew instead, an
   outcome that varies with CP-SAT internals, not something to trust.
   Caught by reasoning it through *before* running anything (Phase 6
   test design), not by a flaky failure — same underlying class of
   issue as the Phase 2 flaky-tie bug this file already documents, just
   a different trigger (same-school non-overlap vs. locked-assignment
   re-solve). Fix: give each such run a `required_qualification_codes`
   entry only *that* run's vehicle has, forcing the solver's hand —
   see `_seed_driver_crew_and_run`'s `qualification_code` param in
   `services/api/tests/test_absences.py` for the pattern. Overlapping
   *time* windows don't need this (two overlapping runs can never share
   one crew regardless of the objective, so both crews are always used
   — only the *pairing* is ambiguous, not *whether* each gets used).
9. **A `Crew` row isn't freed just because its driver is marked
   absent** — `Crew` is a `(driver_id, vehicle_id, service_date)`
   triple with a `UniqueConstraint` on *each* side (one crew per
   driver per day, one crew per vehicle per day). Reporting an absence
   doesn't touch that row at all — the absent driver's vehicle is
   still "claimed" by their own (still-existing) crew for that date.
   First version of the substitute-assignment flow (PR #17) tried
   `POST /crews` to pair a substitute with that "freed" vehicle — every
   attempt 409'd, since the vehicle's own uniqueness constraint doesn't
   care that the original driver is absent, only that a crew row for
   that vehicle+date already exists. Fix: `PATCH /crews/{id}`
   (`routers/crews.py`) repoints the *existing* crew's `driver_id`
   instead of creating a second one — also matches spec §13.2 ("Bus
   724 should remain available for assignment to another qualified
   driver") more literally than the original design did. If a future
   feature needs to "give someone else this same vehicle today," this
   is the pattern — not `POST /crews`.
10. **Frontend verification must run `npm run format:check` (Prettier),
    not just `build`/`lint`/`test`** — a driver-absence-UI commit broke
    `main`'s CI on 2026-09-10 after all three of those passed locally;
    `format:check` is a separate check oxlint/vitest/tsc don't
    subsume, and it was skipped. Also: that same commit was pushed
    directly to `main` instead of through a branch/PR, compounding the
    problem (no CI gate before landing) — a real instance of the exact
    mistake this file's own "Identity / non-negotiable conventions"
    section already warns about. Fixed with a same-day follow-up commit
    once caught; `main` was red for a few minutes in between. Always
    run the *complete* check set `.github/workflows/ci.yml` actually
    runs before pushing, and always branch first — no exceptions
    beyond this file itself.

**Auth (revised mid-session — see PR #6, hardened in PR #14):** httpOnly,
`SameSite=Lax` session cookie (`isd_session`), sliding 30-min
inactivity renewal (`get_current_user` renews Max-Age on every
cookie-authenticated request), 12h absolute cap (JWT `exp` fixed at
login, unaffected by renewal). Separate from the still-unchanged
bearer-token JSON response (60min, used by tests/Swagger/scripts) —
additive, not a replacement. Frontend **never** touches the token —
auth state is just "did `GET /users/me` succeed". CORS: explicit
origin allowlist (never wildcard) + `allow_credentials=True`. Original
plan was an in-memory token; user required refresh-survival +
inactivity-logout, cookie approach is the (more secure) resolution.
**PR #14 closed both remaining ADR 0006 follow-ups**: `POST
/auth/login` is rate-limited (in-memory per-IP fixed window,
`security.LoginRateLimiter`, 429 past threshold); every issued JWT
carries a `jti`, and `POST /auth/logout` now revokes it server-side
via a `revoked_tokens` denylist table (`security.revoke_token`),
checked in `get_current_user` — closes the real gap where a captured
token stayed valid until natural expiry even after "logout." A
refresh-token pair was deliberately not built (see ADR 0006's updated
"Consequences" section for why — the sliding cookie already does that
job for browser sessions).

**DB:** SQLite dev (`services/api/isd_api_dev.db`, gitignored),
PostgreSQL+PostGIS is the stated production target (unused so far — no
Postgres environment exists here). `make_engine()` in `db.py` is the
single source of truth for engine construction (app/tests/bootstrap
script all use it — don't hand-roll a second one).

**Solver↔API boundary:** `services/api/src/isd_api/routers/schedule.py`
— `_to_solver_inputs` builds solver domain objects from DB rows;
`_hard_constraint_violation` re-validates hard constraints for manual
PATCH edits that bypass the solver.

## Status by phase (condensed — full detail in docs/architecture.md)

- **Phase 0** (domain model + ADRs) — Done.
- **Phase 1** (solver MVP) — Done, hardened. 30/30 tests.
- **Phase 2** (persistence + RBAC) — Done. Includes mutation endpoints
  (`PATCH`/`DELETE /schedule/assignments/{id}`, `Assignment.locked` +
  lock-aware re-solve with **partial-day crew availability** — locking
  one assignment only excludes that time range on that crew, not the
  crew's whole day, via `Crew.busy_intervals`), `Driver.max_continuous_minutes`
  enforced as a real CP-SAT hard constraint, ADR 0007 (integrations
  boundary decision, no code yet).
- **Phase 3** (dispatcher console) — **DONE** for its own defined
  scope: login (cookie session), `/schedule` page (run/re-run solver,
  view assignments joined to school/driver/vehicle, lock/unlock,
  delete, crew-reassignment dropdown, **inline crew+run creation for
  the selected date**), `/setup` page (create/list schools,
  qualifications, drivers, vehicles — admin-only creation, RBAC-
  verified live with a real dispatcher-role user). Console is usable
  end to end with **zero raw API calls needed**. Dockerized (both
  images build+run+pass a CI smoke test). "Other roles" is *not* a
  Phase 3 gap — driver app is Phase 4, parent/student is Phase 5, each
  its own phase in the original roadmap.
- **Phase 4** (driver app) — **MVP done** (PR #13, ADR 0008: responsive
  web app in `services/web`, not native — see ADR 0008 for the full
  reasoning, including why this doesn't foreclose a native client
  later). `/driver` page: today's own runs with resolved school/vehicle
  names (`GET /schedule/{date}/my-assignments`, denormalized/driver-
  scoped rather than broadening the admin-only `/runs`,`/crews`,
  `/drivers` endpoints), mark started/completed/no-show (`PATCH
  /schedule/assignments/{id}/status`, audited), native `SpeechSynthesis`
  "read aloud" (spec §9). Role-aware nav (`AppLayout`) and root-redirect
  (`RoleHome` in `App.tsx`). **Along the way fixed a real bug**:
  `LoginPage.tsx` hardcoded its post-login redirect to `/schedule` —
  broke for a driver login now that one exists (found via manual
  browser testing, not by inspection — see the project's own precedent
  of catching real bugs this way). A driver can also report their own
  absence — "Report an absence" section, `POST /drivers/{id}/absences`
  scoped to the signed-in driver's own `driver_id` (the API already
  supported this since Phase 6; this just added the button — see PR
  list below, though this one was mistakenly committed directly to
  `main` rather than through a branch/PR, see gotcha #10). Not yet:
  parent/student views (Phase 5), GPS/live position (ADR 0007, Phase
  6+), offline support.
- **Phase 5** (parent/student app) — **MVP done** (PR #15). Scoped
  directly from the source spec document (`Bus Program Specifications
  Document.docx`, still present in `C:\Users\gmbug\Downloads\` — not
  repo-tracked; read it directly for §3/§4/§17/§18 rather than relying
  on this file's paraphrases) rather than secondhand paraphrases, the
  way every earlier plan this session had to. New `Student`/`Stop`/
  `RidershipOverride` entities + `student_guardians` M2M, manual entry
  only (ADR 0007 precedent, no SIS sync). `/family` page (student/
  parent roles): each linked child's school/stop and today's AM/PM
  ridership (`GET /students/my-family`), declare/override per leg
  (`PATCH /students/{id}/ridership` — also spec §4.5's "late request
  to ride", same mechanism). `/setup` gained Students/Stops sections.
  Ridership overrides are keyed by `(student, service_date, direction)`,
  **not** a `Run` row — there's no recurring `Route` template table
  (ADR 0001 named that intent, never built), so this keeps the whole
  slice out of `Run`/`Assignment`/the solver entirely; see "Gotchas"
  above for a real bug this shipped with and fixed.
  **§4.3, scoped (PR #23)**: `Run` gained `direction` (it had none —
  needed at all to join against `RidershipOverride`, keyed by
  `student, date, direction`); `GET /runs/{id}/expected-riders`
  computes a real rider count as decision support for
  `Run.passenger_count`, `PATCH /runs/{id}` lets a dispatcher apply it
  manually, `ambiguous=true` when >1 run shares a school/date/direction
  (no student-to-specific-run assignment exists) disables Apply on the
  frontend. **This is not spec §4.3's literal behavior** — reading the
  spec text directly (not this file's own prior shorthand) showed §4.3
  is actually stop-sequence route shortening, needing a `Route`/
  stop-sequence model that doesn't exist; that remains genuinely
  undone, named explicitly rather than silently reinterpreted. Not
  yet: automated stop generation (§3.1, needs GIS), §4.3's real
  stop-shortening, cutoff/lock rules (§4.4), live GPS/ETA and
  notifications (§18, Phase 6+).
- **Phase 6** (dynamic rerouting, substitutes, field trips, historical
  learning) — **spec §13 done (backend+UI), §6 done (modulo §7's
  routing-graph dependency), §8 done (persistence + wired into
  routing)**
  (PR #16 backend, PR #17 UI + a real bug fix — see "Gotchas" #9;
  PR #18 GIS slice 1; PR #19 §8 persistence; PR #20 §8 routing wiring;
  PR #21 §6 vehicle dimensions persisted; PR #22 §6 vehicle dimensions
  wired into routing). `DriverAbsence`
  entity (a driver reports their own, or dispatcher/admin reports for
  any driver, `POST /drivers/{id}/absences`; `GET /absences?service_date=`
  for the date-wide overview); `GET /drivers/{id}/substitute-candidates`
  identifies that driver's affected assignments for a date and ranks
  substitutes (school familiarity, same-day workload — see
  `docs/domain-model.md`'s "Phase 6 entities" for the scoring detail
  and why a driver-license-vs-vehicle-type qualification match was
  deliberately left out) with genuine double-bookings and duty-limit
  violations hard-excluded. Completing a substitution: `PATCH
  /crews/{id}` (repoint, when the candidate has no crew of their own
  that date) or the existing `PATCH /schedule/assignments/{id}` (when
  they do) — no `POST /crews` in this flow, see gotcha #9 for why.
  `services/web`'s `SchedulePage` gained a "Driver absences" section:
  report an absence, browse ranked substitutes per affected assignment,
  one-click assign (branches on which of the two above it needs).
  **GIS slice 1 (PR #18)**: `isd_solver.ors_deadhead_estimator` calls
  OpenRouteService's `driving-hgv` profile for a real road-network
  deadhead time; `POST /schedule` wires it in automatically when
  `ISD_API_ORS_API_KEY` is configured, else (the default — CI/tests/
  local dev) falls back to the Phase 1 straight-line estimator, same
  fallback if the live call fails. Chose OpenRouteService over HERE
  (free-tier signup was giving the user trouble) and over self-hosted
  OSRM/GraphHopper (avoids ops burden for a solo founder; self-hosting
  stays an option later if ORS's free tier or precision is outgrown).
  Deliberately NOT in this slice: per-vehicle height/width/weight
  restrictions (`DeadheadEstimator`'s signature is vehicle-agnostic —
  `Callable[[Location, Location], int]` — widening it to take a
  `Vehicle` ripples into every `scheduler.py` call site), §7 turn/
  dead-end safety costs, §8 district-specific overrides, §10 dynamic
  rerouting, §12 field trips, §20 historical learning — all still not
  started, each needs either a routing graph this system doesn't own
  or its own new persisted entity/UI.
  **§8 district geographic knowledge (PR #19)**: `GeographicKnowledgeOverride`
  (`services/api/src/isd_api/routers/geographic_knowledge.py`) —
  transportation_admin/dispatcher record local roadway knowledge
  (flooding, difficult intersections, unsafe turns, invalid
  turnarounds, congestion windows, vehicle-size restrictions,
  preferred entrances, other) via `POST`/`GET /geographic-knowledge`,
  audited. RBAC deliberately matches `DriverAbsence` (both roles can
  create — day-to-day operational knowledge) rather than `Stop`
  (admin-only structural master data). `services/web`'s `/setup` page
  gained a "District geographic knowledge" section, gated on a new
  `canCreateDistrictKnowledge` boolean distinct from the page's
  existing admin-only `canCreate`. Manually verified live against a
  real running server as both dispatcher and transportation_admin
  (see "Environment specifics" below for two real environment quirks
  hit and worked around along the way — neither was a bug in this
  feature's code). **§8 wiring into routing (PR #20)**:
  `isd_solver.avoid_polygons_geojson` + `ors_deadhead_estimator`'s new
  `avoid_polygons` param — `POST /schedule` turns 3 of the 8
  `GeographicKnowledgeOverride` categories (`FREQUENT_FLOODING`,
  `UNSAFE_TURN`, `INVALID_TURNAROUND`) into a real ORS avoid-zone via
  `_HARD_AVOID_CATEGORIES` in `routers/schedule.py`. The other 5
  (`DIFFICULT_INTERSECTION`, `CONGESTION_WINDOW`,
  `VEHICLE_SIZE_RESTRICTED`, `PREFERRED_ENTRANCE`, `OTHER`) are
  deliberately excluded — each needs a mechanism a hard avoid-zone
  can't correctly express (soft cost, time-of-day, per-vehicle, a
  positive-preference waypoint, or too ambiguous to act on), not just
  missing plumbing. **Live-verified with a real ORS key**: fetched a
  real route's geometry, picked a coordinate confirmed to be on the
  actual path, built an avoid-zone around it, and confirmed the
  returned duration measurably changed (12→13 min) — proves ORS
  actually honors the option, not just that the request doesn't error.
  This closes out spec §8 as originally scoped (persist the knowledge,
  then apply it to routing) — everything else in Phase 6 (§7, §10,
  §12, §20, plus per-vehicle restrictions within §6) is still open.
  **§6 vehicle dimensions (PR #21)**: `Vehicle` gains
  `length_m`/`width_m`/`height_m`/`weight_kg` end-to-end (domain
  dataclass, DB column + migration, schema, `POST /vehicles`,
  `SetupPage.tsx`'s Vehicles form) — mapped directly to ORS's HGV
  restriction params, so real usable data, not speculative fields.
  Deliberately not persisting turning radius (no ORS param for it),
  wheelchair config (already modeled via `Qualification`), or vehicle
  type (no per-vehicle ORS profile switching exists). **Persistence
  only** — `DeadheadEstimator` still doesn't take a `Vehicle`
  argument, so nothing in the scheduler reads these dimensions yet;
  wiring them in needs restructuring `scheduler.py`'s pairwise-ordering
  loop (currently calls the estimator once per job-pair shared across
  every candidate crew, not once per (job-pair, crew)) — a real,
  separate design decision, named as the next follow-up. Manually
  verified live: created a vehicle with all four dimensions and one
  without, confirmed both round-trip correctly and the fields are
  genuinely optional.
  **§6 wired into routing (PR #22)** — `DeadheadEstimator` widened to
  `Callable[[Location, Location, Vehicle], int]`;
  `scheduler.py`'s pairwise-ordering loop now calls it once per
  (job-pair, crew), not once per job-pair shared across every
  candidate crew — the actual bug this fixes, confirmed with a new
  test proving two vehicles with different deadhead values for the
  same job pair genuinely get different treatment, not a shared
  number. `ors_deadhead_estimator` builds `options.profile_params.restrictions`
  from a vehicle's dimensions (weight kg→tons); cache key gained a
  vehicle-restriction-signature component since results now vary by
  vehicle, not just location. Also fixed the actual gotcha #7 instance
  this slice depended on: `routers/schedule.py`'s `SolverVehicle(...)`
  constructor call wasn't passing the dimension fields at all — PR #21
  added them to both models but nothing wired the router's
  constructor, so this PR would have shipped a no-op without catching
  it directly by reading `_to_solver_inputs`. **Live verification
  caught a real bug before it shipped**: some published ORS docs
  describe a required top-level `vehicle_type` field alongside
  `restrictions`; the live v2 directions API rejects it with a 400 —
  removed it, `restrictions` alone is accepted. This closes out spec
  §6 as far as an external point-to-point routing API can express it —
  only §7 (turn/dead-end costs, needs a routing graph) remains, a
  genuinely different technical approach, not a follow-up to this.
- **Auth hardening** (PR #14) — **Done.** Both ADR 0006 follow-ups
  closed: login rate limiting, logout token revocation. See "Auth"
  under Architecture above for detail.
- **CI**: `.github/workflows/ci.yml`, 4 jobs (solver/api/web/docker),
  runs on every push to `main` and every PR. Currently green (verified
  via `gh pr checks --watch` on PR #22, not just assumed).

## PRs merged this session (chronological)

1. #1 `chore/lint-tooling` — ruff+mypy for solver+api
2. #2 `refactor/db-connection-layer` — `make_engine()` factory, pool tuning
3. #3 `feat/assignment-mutation-and-locking` — PATCH/DELETE assignments, `Assignment.locked`
4. #4 `feat/enforce-driver-continuous-duty-limit` — `max_continuous_minutes` CP-SAT constraint
5. #5 `docs/adr-0007-external-systems-integration` — ADR 0007 (docs only)
6. #6 `feat/phase3-dispatcher-console-mvp` — `services/web` created, login+schedule view, cookie auth backend
7. #7 `chore/ci-setup` — `.github/workflows/ci.yml`, `.gitattributes`, fixed isd_solver dep + numpy/mypy bugs
8. #8 `feat/crew-reassignment-ui` — Crew `<select>` on SchedulePage, fixed stale `explanation_text` bug
9. #9 `feat/setup-page-master-data` — `/setup` page (schools/quals/drivers/vehicles)
10. #10 `feat/inline-crew-run-creation` — inline crew/run forms on SchedulePage; console now usable with zero raw API calls
11. #11 `feat/docker-deployment-config` — Dockerfiles, `docker-compose.yml`, CI `docker` job; fixed a volume-permissions bug and a compose env-var footgun (both found by actually running the containers, not just building them)
12. #12 `feat/partial-day-crew-availability` — `Crew.busy_intervals` (solver) + `routers/schedule.py` populating it from locked assignments instead of excluding the whole crew; replaced two api tests whose assumptions no longer held (one had become a genuine, flaky tie in the solver's own objective — confirmed it happened to pass once anyway, not trusted)
13. #13 `feat/phase4-driver-app-mvp` — ADR 0008 (driver client platform), `Assignment.status`/`status_updated_at` + migration, `GET /schedule/{date}/my-assignments` + `PATCH .../status` (driver-scoped), `services/web` `/driver` page + role-aware nav/redirect, fixed `LoginPage`'s hardcoded `/schedule` redirect bug
14. #14 `feat/auth-hardening-rate-limit-revocation` — `security.LoginRateLimiter` (per-IP, in-memory) on `POST /auth/login`; `jti` claim on every issued JWT + `revoked_tokens` denylist table + `security.revoke_token`, called from `POST /auth/logout`, checked in `get_current_user`; closed both ADR 0006 follow-ups, updated that ADR's "Consequences" section
15. #15 `feat/phase5-student-ridership-mvp` — `Student`/`Stop`/`RidershipOverride`/`student_guardians` (manual entry, scoped from the real spec doc — see "Phase 5" above), `GET /students/my-family` + `PATCH /students/{id}/ridership`, `services/web` `/family` page + `/setup` Students/Stops sections; fixed a real bug where `POST /users` silently dropped `student_id` (see "Gotchas" above)
16. #16 `feat/phase6-driver-absence-substitutes` — `DriverAbsence`, `GET /drivers/{id}/substitute-candidates` (school-familiarity + same-day-workload ranking, hard-excludes double-bookings/duty-limit violations), backend-only (see "Phase 6" above); test design deliberately avoided a same-school/non-overlapping-runs solver-tie trap (see "Gotchas" above)
17. #17 `feat/phase6-absence-substitute-ui` — `GET /absences?service_date=` (date-wide overview), `PATCH /crews/{id}` (driver repoint — added mid-PR after manual testing caught `POST /crews` 409ing every time, see "Gotchas" #9), `services/web` "Driver absences" section on `SchedulePage` (report absence, browse/act on ranked substitutes)
18. #18 `feat/phase6-gis-ors-deadhead-estimator` — Phase 6 GIS slice 1: `isd_solver.ors_deadhead_estimator` (OpenRouteService `driving-hgv` profile), wired into `POST /schedule` opt-in via `ISD_API_ORS_API_KEY`, falls back to the straight-line estimator when unset or on API failure; also fixed a stale doc claim in `architecture.md`/`domain-model.md` that substitute assignment still used `POST /crews` (PR #17 already replaced that with `PATCH /crews/{id}`)
19. #19 `feat/phase6-district-geographic-knowledge` — Phase 6 spec §8: `GeographicKnowledgeOverride` entity, `POST`/`GET /geographic-knowledge` (transportation_admin + dispatcher, audited), `services/web` "District geographic knowledge" section on `SetupPage`; persistence only, not yet wired into route calculations (spec §8's own deferral)
20. #20 `feat/phase6-geo-knowledge-routing-integration` — Phase 6 spec §8 wiring: `isd_solver.avoid_polygons_geojson` + `ors_deadhead_estimator`'s new `avoid_polygons` param, `POST /schedule` turns 3 of 8 `GeographicKnowledgeOverride` categories into a real ORS avoid-zone (`_HARD_AVOID_CATEGORIES` in `routers/schedule.py`), live-verified against a real ORS key to confirm a forced detour actually changes trip duration
21. #21 `feat/phase6-vehicle-dimensions` — Phase 6 spec §6 slice 2: `Vehicle` gains `length_m`/`width_m`/`height_m`/`weight_kg` end-to-end (domain, DB, schema, router, `SetupPage.tsx`), mapped to ORS's HGV restriction params; persistence only, `DeadheadEstimator` doesn't consume them yet
22. #22 `feat/phase6-vehicle-dimensions-routing-wiring` — Phase 6 spec §6 completion: `DeadheadEstimator` widened to carry a `Vehicle`, `scheduler.py`'s pairwise loop restructured to call it per-crew, `ors_deadhead_estimator` builds ORS restrictions from vehicle dimensions; fixed the `SolverVehicle(...)` constructor gap this depended on; live verification caught a real bug (published docs' `vehicle_type` field is rejected by the live API) before it shipped
23. #23 `feat/ridership-expected-riders` — spec §4.3, scoped: `Run.direction`, `PATCH /runs/{id}`, `GET /runs/{id}/expected-riders` (decision support for `passenger_count` from real `Student`/`RidershipOverride` data, flags `ambiguous` when >1 run shares a school/date/direction); explicitly NOT §4.3's literal stop-sequence route shortening, which needs a `Route` model this system doesn't have — scope boundary documented, not silently reinterpreted
24. #24 `feat/gps-live-position` — spec §9/§18, ADR 0009: `VehiclePosition` (one row per crew, latest position only), `PUT /drivers/{id}/position` (driver's own tablet, browser Geolocation API, auto-reports while a run is `in_progress` — no dedicated GPS/AVL hardware/vendor needed, closing the "flag to the user" note from the prior checkpoint without actually needing to ask), `GET /schedule/{date}/fleet-positions` (dispatcher, polled every 20s on `SchedulePage`), `GET /students/{id}/bus-position` (family "Locate bus," `available`/`ambiguous`-shaped like PR #23's expected-riders); notifications (the rest of §18) and turn-by-turn nav/incident reporting/dispatch messaging (the rest of §9) explicitly named as still-unbuilt, not implied done
25. #25 `feat/phase6-field-trips-backend` — spec §12, backend only: `FieldTrip` (not run through the CP-SAT solver — driver/vehicle assignment is a manual decision, spec §21, same shape as §13's substitute ranking), `POST`/`GET`/`GET {id}`/`PATCH /field-trips`, `GET /field-trips/{id}/conflicts` (§12.1 — checks overlapping regular-route `Assignment`s and other field trips only, no Training/Maintenance entity exists to check against); §12.2's "delay management" reuses the same conflicts endpoint rather than a new mechanism. First slice: same-day trips only (overnight rejected with a 400), backend only — UI followed in PR #26, same split as #16→#17
26. #26 `feat/phase6-field-trips-ui` — spec §12 UI: new `/field-trips` page (add a trip, list by date, pick a candidate driver/vehicle, check conflicts, assign when clear, step through the status lifecycle). **Manual browser verification caught and fixed a real bug**: `formatDateTime` ran a naive backend timestamp through `new Date()` then `getUTCHours()`/`getUTCMinutes()`, which silently applied the browser's local-UTC offset (06:30 entered displayed as 11:30) — fixed by extracting the `HH:MM` digits directly instead of going through `Date`/timezone conversion, matching the backend's own naive-wall-clock design. Verified live end-to-end: a trip overlapping a real solved regular route showed the conflict and disabled Assign; a non-overlapping trip showed "No conflicts" and Assign correctly PATCHed the driver/vehicle
27. #27 `feat/phase6-historical-duration-learning` — spec §20: `GET /runs/observed-duration?school_id=&direction=`, computed entirely from data already persisted — a completed `Assignment`'s actual start/end are read off its own `status_changed` audit entries (spec §14), no new breadcrumb/history table. Runs have no recurring-route identity, so "this route" is approximated as completed runs sharing a `(school_id, direction)` pair across any `service_date`. Decision support only (spec §21): `SchedulePage`'s "Add run" form gets a "Check observed duration" / "Use average" flow, never auto-applied. Manually verified live: adjusted real audit timestamps to simulate a 48-minute actual duration, confirmed the UI showed it and "Use average" correctly filled the duration field
28. #28 `feat/phase6-transportation-announcements` — spec §9/§18: `Announcement` (`message`, `category` — general/delay/substitution/route_change, informational label only — `audience` — all/family/driver), `POST`/`GET /announcements` (management) + `GET /announcements/mine` (audience-filtered). Deliberately always human-authored, never auto-detected — no ETA engine, no automatic event-to-notification pipeline exists to turn a real driver-swap (§13) into a targeted family notice, so that targeting problem is named as a follow-up, not attempted. District-wide only, no per-school scoping. `/setup` gained an "Announcements" section; `DriverPage` shows "Messages from dispatch," `FamilyPage` shows "Transportation announcements." Manually verified live: posted a family-audience notice and a driver-audience notice, confirmed each surfaced only to its intended audience through the actual browser

## Key files (current state, post-PR #28)

- `services/api/src/isd_api/security.py` — cookie auth (`SESSION_COOKIE_NAME`, `create_session_token`, `set_session_cookie`/`clear_session_cookie`, `get_current_user` does dual header-or-cookie auth + renewal + revocation check), `LoginRateLimiter`/`login_rate_limiter`, `revoke_token`
- `services/api/src/isd_api/routers/auth.py` — login rate-limited + sets cookie + returns bearer token; `POST /auth/logout` (still no auth required — a no-op if nothing to revoke, but revokes the current token if one is present)
- `services/api/src/isd_api/routers/schedule.py` — `POST /schedule` (lock-aware), `PATCH`/`DELETE /schedule/assignments/{id}`, `GET /schedule/{date}/assignments`, `GET /schedule/{date}/my-assignments` + `PATCH /schedule/assignments/{id}/status` (driver-scoped, Phase 4), `_hard_constraint_violation` helper
- `services/api/src/isd_api/config.py` — `session_inactivity_minutes=30`, `session_absolute_max_hours=12`, `cors_allowed_origins`, `login_rate_limit_attempts=10`/`login_rate_limit_window_seconds=300`, DB pool settings, `ors_api_key`/`ors_base_url`/`ors_profile` (Phase 6 GIS slice 1 — unset key means the straight-line estimator is used, the default for CI/tests/local dev)
- `services/solver/src/isd_solver/domain.py` — `DeadheadEstimator = Callable[[Location, Location, Vehicle], int]` (widened in PR #22); `straight_line_deadhead_estimator` (Phase 1 default/fallback, ignores `vehicle`), `osrm_deadhead_estimator` (Phase 1 scaffold, never wired into `services/api`, ignores `vehicle`), `ors_deadhead_estimator` (the one `routers/schedule.py` actually wires in when `ISD_API_ORS_API_KEY` is set — `avoid_polygons` param is spec §8's routing wiring point, `vehicle` param is spec §6's, cache key includes a vehicle-restriction signature), `avoid_polygons_geojson` (pure geometry helper, points → GeoJSON MultiPolygon) — the three estimators share the dependency-injected-HTTP-call + cache + fallback-or-raise pattern, see `services/solver/tests/test_ors_deadhead_estimator.py` for the test template
- `services/api/src/isd_api/models.py` — `RevokedToken` (jti denylist), `Assignment.status`/`AssignmentStatus`, `Student`/`Stop`/`RidershipOverride`/`student_guardians` (Phase 5), `User.student_id`, `DriverAbsence`/`AbsenceReason` (Phase 6)
- `services/api/src/isd_api/routers/students.py` — `POST`/`GET`/`PATCH /students`, `POST /students/{id}/guardians`, `GET /students/my-family`, `PATCH /students/{id}/ridership` — all the Phase 5 RBAC ownership-check logic lives here
- `services/api/src/isd_api/routers/stops.py` — `POST`/`GET /stops`, admin/dispatcher only
- `services/api/src/isd_api/routers/absences.py` — `POST`/`GET /drivers/{id}/absences`, `GET /absences?service_date=` (all-drivers overview, `all_absences_router`, second router in this file), `GET /drivers/{id}/substitute-candidates` + `_rank_substitute_candidates` (Phase 6 ranking heuristic, private helper)
- `services/api/src/isd_api/routers/crews.py` — `POST`/`GET /crews`, `PATCH /crews/{id}` (driver-only repoint — see Gotchas #9 for why this exists instead of a second `POST /crews`)
- `services/api/src/isd_api/routers/geographic_knowledge.py` — `POST`/`GET /geographic-knowledge` (spec §8 persistence — transportation_admin + dispatcher, audited); `routers/schedule.py`'s `_HARD_AVOID_CATEGORIES` is where 3 of the 8 categories actually get consumed by routing
- `services/api/src/isd_api/routers/vehicles.py` — `POST`/`GET /vehicles`; `create_vehicle`'s explicit constructor kwargs carry `Vehicle`'s `length_m`/`width_m`/`height_m`/`weight_kg` (spec §6, now consumed by routing — see `schedule.py`'s `SolverVehicle(...)` for the second gotcha #7 spot this depended on)
- `services/api/src/isd_api/routers/runs.py` — `POST`/`GET /runs`, `PATCH /runs/{id}` (passenger_count only), `GET /runs/{id}/expected-riders` (spec §4.3 decision support — not the spec's literal stop-shortening behavior, see "Status by phase" Phase 5 entry above)
- `services/api/src/isd_api/routers/positions.py` — `PUT /drivers/{id}/position` (driver self-report, `driver_router`), `GET /schedule/{date}/fleet-positions` (dispatcher/admin, `fleet_router` — two routers in one file since neither fits the other's prefix); `GET /students/{id}/bus-position` lives in `routers/students.py` instead, since it needs that file's guardian/self RBAC helper
- `services/api/src/isd_api/models.py` — `VehiclePosition` (ADR 0009: `crew_id` unique, one row per crew, overwritten in place — no breadcrumb trail); `FieldTrip`/`TripStatus` (spec §12: direct `assigned_driver_id`/`assigned_vehicle_id` FKs, not a `Crew` pairing — not run through the solver)
- `services/api/src/isd_api/routers/field_trips.py` — `POST`/`GET`/`GET {id}`/`PATCH /field-trips`, `GET /field-trips/{id}/conflicts` (same-day-only minute-of-day overlap check against regular `Assignment`s and other `FieldTrip`s — module docstring explains what it deliberately doesn't check and why)
- `services/web/src/pages/FieldTripsPage.tsx` — `/field-trips`: add/list trips, candidate driver/vehicle + conflict check + assign, status lifecycle `<select>`. `formatDateTime` extracts `HH:MM` via regex, deliberately NOT `new Date(...).getUTCHours()` — see PR #26's real bug fix if tempted to "simplify" this back
- `services/api/src/isd_api/routers/runs.py` — `GET /runs/observed-duration` (spec §20): reads a completed `Assignment`'s actual start/end off its own `status_changed` `AuditLogEntry` rows rather than any new column — if extending this, resist adding an `actual_start_at`/`actual_end_at` column before checking whether the audit log already has what's needed
- `services/api/src/isd_api/routers/announcements.py` — `POST`/`GET /announcements` (management, transportation_admin/dispatcher), `GET /announcements/mine` (audience-filtered: driver role → all+driver, student/parent → all+family). Always human-authored (spec §9/§18) — no auto-generation from real events (driver-swaps, delays) exists; that targeting problem is a named follow-up, not built
- `services/api/src/isd_api/main.py` — `CORSMiddleware` config, router registration (check here first if a new router's routes 404 — it needs an `app.include_router(...)` call too, not just existing as a file)
- `services/solver/src/isd_solver/scheduler.py` — CP-SAT model, duty-limit pairwise constraints, busy-interval constraints
- `services/solver/src/isd_solver/domain.py` — `Crew.busy_intervals` (validated within `available_window`)
- `services/web/src/api/client.ts` — hand-written typed fetch wrapper, `credentials: 'include'` everywhere, `ApiError` class
- `services/web/src/api/types.ts` — hand-written types mirroring backend schemas
- `services/web/src/auth/AuthContext.tsx` — no token storage, just `GET /users/me` on mount
- `services/web/src/auth/ProtectedRoute.tsx` — role-gated route wrapper
- `services/web/src/pages/SchedulePage.tsx` — main dispatcher view
- `services/web/src/pages/SetupPage.tsx` — schools/quals/drivers/vehicles create+list
- `services/web/src/pages/DriverPage.tsx` — Phase 4 driver view (`/driver`): run cards, status buttons, read-aloud
- `services/web/src/pages/FamilyPage.tsx` — Phase 5 student/parent view (`/family`): per-child cards, AM/PM ridership toggles
- `services/web/src/layout/AppLayout.tsx` — header, role-conditional nav (Schedule/Setup for dispatcher/admin, My Runs for driver, My Family for student/parent), logout
- `services/web/src/App.tsx` — routes + `RoleHome` (role-aware `/` redirect: driver → `/driver`, student/parent → `/family`, else → `/schedule`)
- `services/api/Dockerfile`, `services/web/Dockerfile`, `services/web/nginx.conf`, `docker-compose.yml`, `.dockerignore` (root, api's build context) / `services/web/.dockerignore`
- `docs/architecture.md` — system diagram + phase table + known gaps — **keep updated per PR**
- `docs/adr/0001`–`0008` — architecture decision records

## Exact next step (as of this checkpoint)

Every PR through #28 is **merged**, CI green, local `main` synced
(commit `9850d3c`). The user said explicitly: **tackle the entire
remaining candidate list, continuing until it's done or something new
needs deciding** — not "pick one," work through all of them.

Everything that was ever on this session's candidate list is now
**done** except two items, both deliberately saved for last because
they need a routing *graph* this system doesn't own (ADR 0007), a
materially different technical approach than anything built in Phase
6 so far — real vendor/architecture research, not another slice of
the same pattern:

1. **§7 turn/dead-end safety costs** — routing-graph-level segment/
   turn costs; this system only ever calls a point-to-point directions
   API (ORS), which has no concept of "penalize this specific turn."
2. **§10 dynamic rerouting** — live rerouting around closures/
   incidents needs the same graph, plus a live-incident data source
   this system doesn't have either.

**Asked the user directly (2026-09-14): deferred, deliberately, not
guessed at.** Presented three options (self-host OSRM/Valhalla, research
a commercial routing API with graph-level controls, or defer) — the
user picked **defer**. Phase 6's existing ORS-based routing (§6/§8)
already gives legal/safe HGV routing (weight/height/width restrictions,
flood/unsafe-turn avoid-zones); §7/§10 are refinements beyond that
safety baseline, not a gap in it. Revisit only if this becomes a real,
felt operational pain point — don't self-host or shop for a vendor
speculatively before then.

Smaller, non-blocking items still open, each its own scoped follow-up
whenever picked up (not urgent, not part of the original "tackle
everything" list's scope, listed here so they aren't lost):
- The 5 excluded §8 categories (difficult intersection, congestion
  window, vehicle-size restriction, preferred entrance, other) — each
  excluded for a specific principled reason already documented
  (`docs/domain-model.md`'s "Phase 6 entities").
- Field trips: overnight trips, destination profiles (§12.3), a
  duration-learning rollup for `FieldTrip.actual_return_at` (§20).
- Announcements: per-school scoping, auto-generated substitution
  notices from real driver-swap events (needs family-targeting logic).
- **§9 incident reporting / vehicle defect reporting — up next.**
  Tractable and self-contained (no dependency on the deferred routing
  graph, unlike turn-by-turn navigation, which genuinely is blocked by
  the §7/§10 decision above and stays deferred with it).

## Environment specifics (this machine)

- Windows; PowerShell primary, git-bash for the Bash tool (separate
  PATH, separate line-ending behavior — see gotchas above).
- Python 3.12 (Windows Store install). numpy currently pinned at
  2.5.2 locally (deliberately upgraded mid-session to match CI's
  fresh resolution and reproduce/fix the mypy bug for real, not just
  in theory).
- Dev servers: `python -m uvicorn isd_api.main:app --port 8000` (from
  `services/api`) + `npm run dev` (from `services/web`, port 5173,
  needs the node PATH export above). Both started via the Bash tool
  with `run_in_background: true`, stopped via `TaskStop` when done.
- Manual browser testing via `mcp__Claude_Browser__*` tools. Working
  pattern: `preview_start` → `read_page` (not `screenshot` — the pane
  is often hidden/times out) → `form_input` for text fields →
  `computer` `left_click` with a `ref` for buttons (works once the tab
  is fronted via `tabs_select` if the pane was hidden) → `tabs_close` +
  `TaskStop` cleanup at the end. **Finish all source edits before
  starting the click-through, not during** — Vite's HMR hot-reloads
  the page live, and editing `SchedulePage.tsx` mid-interaction (Phase
  6 UI session) silently reset component state (the substitute-panel
  results, the service-date field) between clicks, which looked like
  broken click handling for several tool calls before the actual cause
  (still-running HMR from an in-progress fix) was obvious. If a click
  stops producing a network request partway through a verification
  pass and nothing else changed, check whether a file edit landed in
  between rather than assuming the click tooling failed.
- `isd_api_dev.db` (default dev DB path) has been avoided entirely
  since the Phase 4 → auth-hardening boundary, because it's wedged
  behind the "ghost process" gotcha above (`rm`/`del` fails with
  "Device or resource busy", port 8000 stays LISTENING under an
  unkillable PID). Both the auth-hardening and Phase 5 verification
  passes used a fresh, differently-named scratch DB + port 8001
  instead (`verify_dev.db`, then `phase5_verify.db`), cleaned up after
  each. This pattern is now proven twice — keep using it rather than
  re-attempting to free port 8000 or `isd_api_dev.db`. Whatever state
  `isd_api_dev.db` itself is actually in by now is unknown and
  irrelevant — don't build on it as a fixture.
- `.claude/launch.json` (gitignored, not repo-tracked) has an
  `isd-web` entry pointing at `http://localhost:5173` for the Browser
  tool's `preview_start` — if a Vite dev server is already running on
  that port from a prior turn, `preview_start` attaches to it instead
  of starting a new one (`"url"` config, no `runtimeExecutable`).
- **The "ghost process" gotcha (#6 above) also hits `npm run dev`
  (Vite/node), not just uvicorn.** Discovered during PR #19's manual
  verification: a `npm run dev` backgrounded via the Bash tool with a
  different `VITE_API_BASE_URL` left a still-running process squatting
  on port 5173 with the *old* env var baked in; a second `npm run dev`
  attempt silently fell through to 5174, then 5175 (Vite's own
  fallback-port behavior), while the Browser pane kept talking to the
  stale 5173 ghost with the wrong API port compiled in — looked like a
  CORS failure (browser console literally said "blocked by CORS
  policy") until traced to the mismatched port. Same fix as the
  uvicorn case: don't hunt the PID, just point the *next* API instance
  at whatever port the still-live ghost's frontend already expects
  (simplest fix in the moment), or use a genuinely fresh port pair for
  both frontend and backend together, not just the backend.
- **A `.test`-TLD email (e.g. `admin@geo-verify.test`) as bootstrap/
  scratch test data crashes `GET /users/me` with a 500**, not the 401/
  CORS error it superficially looks like in a browser's console. Root
  cause: pydantic's `EmailStr` (via `email-validator`) rejects `.test`
  as a reserved/special-use TLD at **response serialization** time
  (`UserRead.email`), not at input validation — so login (`POST
  /auth/login`, which never re-serializes the email) succeeds fine,
  and the crash only surfaces on the *next* request that reads that
  user's own record back, which a browser reports as a CORS failure
  (no CORS headers survive an unhandled 500 in this middleware
  ordering) — a red herring that cost real debugging time during PR
  #19's manual verification before the actual server log traceback was
  checked. Use `.org`/`.com`/`example.org`-style scratch emails for any
  bootstrap/manual-testing user, never `.test`/`.invalid`/`.example`
  reserved TLDs, even though they're the "correct" RFC 2606 choice for
  throwaway data in most other contexts.

## Memory system

Persistent cross-session memory lives at
`C:\Users\gmbug\.claude\projects\D--Projects-isd-bus-routing\memory\`
(`MEMORY.md` index + per-topic files) — that's a **different**,
complementary mechanism to this file: private to Claude, not
repo-tracked. This file is repo-tracked so it survives even without
access to that memory directory (a fresh branch, a different machine,
a clone). Keep both updated; they should never contradict each other.
