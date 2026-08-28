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
  for every PR this session (9 so far) with no exceptions except
  this file.
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

**Auth (revised mid-session — see PR #6):** httpOnly, `SameSite=Lax`
session cookie (`isd_session`), sliding 30-min inactivity renewal
(`get_current_user` renews Max-Age on every cookie-authenticated
request), 12h absolute cap (JWT `exp` fixed at login, unaffected by
renewal). Separate from the still-unchanged bearer-token JSON response
(60min, used by tests/Swagger/scripts) — additive, not a replacement.
Frontend **never** touches the token — auth state is just "did
`GET /users/me` succeed". CORS: explicit origin allowlist (never
wildcard) + `allow_credentials=True`. Original plan was an in-memory
token; user required refresh-survival + inactivity-logout, cookie
approach is the (more secure) resolution.

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
  lock-aware re-solve), `Driver.max_continuous_minutes` enforced as a
  real CP-SAT hard constraint, ADR 0007 (integrations boundary
  decision, no code yet).
- **Phase 3** (dispatcher console, MVP) — **IN PROGRESS**:
  - Done: login (cookie session), `/schedule` page (run/re-run solver,
    view assignments joined to school/driver/vehicle, lock/unlock,
    delete, crew-reassignment dropdown), `/setup` page (create/list
    schools, qualifications, drivers, vehicles — admin-only creation,
    RBAC-verified live with a real dispatcher-role user).
  - **Not done / current work**: creating Crews and Runs (the two
    date-scoped entities) still requires raw API calls — no UI yet.
    Planned as inline forms on `SchedulePage.tsx` (reuse its existing
    date picker/state), split out of PR #9 to keep it reviewable. **See
    "Next step" below.**
  - Also not done: other roles (driver/school_admin/parent) in the
    console; any deployment/Docker config for any service.
- **Phases 4–6** — Not started (driver app, parent/student app,
  dynamic rerouting/substitutes/field trips/historical learning).
- **CI**: `.github/workflows/ci.yml`, 3 jobs (solver/api/web), runs on
  every push to `main` and every PR. Currently green.

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

## Key files (current state, post-PR #9)

- `services/api/src/isd_api/security.py` — cookie auth (`SESSION_COOKIE_NAME`, `create_session_token`, `set_session_cookie`/`clear_session_cookie`, `get_current_user` does dual header-or-cookie auth + renewal)
- `services/api/src/isd_api/routers/auth.py` — login sets cookie + returns bearer token; `POST /auth/logout` (no auth required)
- `services/api/src/isd_api/routers/schedule.py` — `POST /schedule` (lock-aware), `PATCH`/`DELETE /schedule/assignments/{id}`, `GET /schedule/{date}/assignments`, `_hard_constraint_violation` helper
- `services/api/src/isd_api/config.py` — `session_inactivity_minutes=30`, `session_absolute_max_hours=12`, `cors_allowed_origins`, DB pool settings
- `services/api/src/isd_api/main.py` — `CORSMiddleware` config
- `services/solver/src/isd_solver/scheduler.py` — CP-SAT model, duty-limit pairwise constraints
- `services/web/src/api/client.ts` — hand-written typed fetch wrapper, `credentials: 'include'` everywhere, `ApiError` class
- `services/web/src/api/types.ts` — hand-written types mirroring backend schemas
- `services/web/src/auth/AuthContext.tsx` — no token storage, just `GET /users/me` on mount
- `services/web/src/auth/ProtectedRoute.tsx` — role-gated route wrapper
- `services/web/src/pages/SchedulePage.tsx` — main dispatcher view
- `services/web/src/pages/SetupPage.tsx` — schools/quals/drivers/vehicles create+list
- `services/web/src/layout/AppLayout.tsx` — header, nav (Schedule/Setup links), logout
- `docs/architecture.md` — system diagram + phase table + known gaps — **keep updated per PR**
- `docs/adr/0001`–`0007` — architecture decision records

## Exact next step (as of this checkpoint)

Add inline **Crew-creation** and **Run-creation** forms to
`services/web/src/pages/SchedulePage.tsx`, scoped to the currently
selected `serviceDate`:

- **"Add crew" form**: driver `<select>` (from existing `drivers`
  state), vehicle `<select>` (from existing `vehicles` state),
  `available_window_earliest`/`latest` (default 0/1439 or simple
  number inputs) → `POST /crews` via a new `api.createCrew()` (add to
  `client.ts` + a `CrewCreate` type in `types.ts`, mirroring the
  `SchoolCreate`/`DriverCreate` pattern from PR #9). RBAC:
  `transportation_admin` **and** `dispatcher` (both — unlike the Setup
  page's admin-only forms; matches `crews.py`'s `_WRITE_ROLES`).
- **"Add run" form**: school `<select>` (from existing `schools`
  state), `window_earliest`/`latest`, `duration_minutes`,
  `buffer_minutes`, `passenger_count`, `required_qualification_codes`
  (checkboxes filtered to `kind === 'vehicle_capability'`, reuse the
  pattern from `SetupPage.tsx`) → `POST /runs` via a new
  `api.createRun()`. RBAC: `transportation_admin` **and** `dispatcher`.
- After either creation, call the existing `loadAll(serviceDate)` to
  refresh.
- New tests in `SchedulePage.test.tsx`: crew creation calls the API
  and reloads; run creation calls the API and reloads; a validation
  error (e.g. `window_earliest > window_latest`) surfaces the
  backend's message.
- **Manual browser verification required** (standing project rule for
  UI changes) — start both dev servers, exercise the real flow,
  confirm server-side persistence via a direct `curl`, stop servers
  when done.
- Branch: `feat/inline-crew-run-creation` (or similar).
- After merging: update `docs/architecture.md`'s Phase 3 row (remove
  the "creating crews/runs..." caveat), update this file, update
  persistent memory (`project_isd_bus_routing_overview.md`).
- **Beyond that**, no explicit user direction yet — likely candidates:
  other roles' console views, or deployment/Docker config (both
  flagged as open in `docs/architecture.md`).

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
  `TaskStop` cleanup at the end.
- Local dev DB already has: admin user `dispatcher@example.org` /
  `phase3-testing` (`transportation_admin`); a real dispatcher-role
  test user `realdispatcher@example.org` / `dispatcher123`; a school,
  a few drivers/vehicles, and seed runs/crews for `2026-08-31` from
  manual testing.

## Memory system

Persistent cross-session memory lives at
`C:\Users\gmbug\.claude\projects\D--Projects-isd-bus-routing\memory\`
(`MEMORY.md` index + per-topic files) — that's a **different**,
complementary mechanism to this file: private to Claude, not
repo-tracked. This file is repo-tracked so it survives even without
access to that memory directory (a fresh branch, a different machine,
a clone). Keep both updated; they should never contradict each other.
