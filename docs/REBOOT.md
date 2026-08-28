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
   "Device or resource busy") for that verification pass instead.

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
  of catching real bugs this way). Not yet: parent/student views (Phase
  5), absence reporting, GPS/live position (ADR 0007, Phase 6+),
  offline support.
- **Phases 5–6** — Not started (parent/student app, dynamic
  rerouting/substitutes/field trips/historical learning).
- **Auth hardening** (PR #14) — **Done.** Both ADR 0006 follow-ups
  closed: login rate limiting, logout token revocation. See "Auth"
  under Architecture above for detail.
- **CI**: `.github/workflows/ci.yml`, 4 jobs (solver/api/web/docker),
  runs on every push to `main` and every PR. Currently green (verified
  via `gh pr checks --watch` on PR #14, not just assumed).

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

## Key files (current state, post-PR #14)

- `services/api/src/isd_api/security.py` — cookie auth (`SESSION_COOKIE_NAME`, `create_session_token`, `set_session_cookie`/`clear_session_cookie`, `get_current_user` does dual header-or-cookie auth + renewal + revocation check), `LoginRateLimiter`/`login_rate_limiter`, `revoke_token`
- `services/api/src/isd_api/routers/auth.py` — login rate-limited + sets cookie + returns bearer token; `POST /auth/logout` (still no auth required — a no-op if nothing to revoke, but revokes the current token if one is present)
- `services/api/src/isd_api/routers/schedule.py` — `POST /schedule` (lock-aware), `PATCH`/`DELETE /schedule/assignments/{id}`, `GET /schedule/{date}/assignments`, `GET /schedule/{date}/my-assignments` + `PATCH /schedule/assignments/{id}/status` (driver-scoped, Phase 4), `_hard_constraint_violation` helper
- `services/api/src/isd_api/config.py` — `session_inactivity_minutes=30`, `session_absolute_max_hours=12`, `cors_allowed_origins`, `login_rate_limit_attempts=10`/`login_rate_limit_window_seconds=300`, DB pool settings
- `services/api/src/isd_api/models.py` — `RevokedToken` (jti denylist), `Assignment.status`/`AssignmentStatus`
- `services/api/src/isd_api/main.py` — `CORSMiddleware` config
- `services/solver/src/isd_solver/scheduler.py` — CP-SAT model, duty-limit pairwise constraints, busy-interval constraints
- `services/solver/src/isd_solver/domain.py` — `Crew.busy_intervals` (validated within `available_window`)
- `services/web/src/api/client.ts` — hand-written typed fetch wrapper, `credentials: 'include'` everywhere, `ApiError` class
- `services/web/src/api/types.ts` — hand-written types mirroring backend schemas
- `services/web/src/auth/AuthContext.tsx` — no token storage, just `GET /users/me` on mount
- `services/web/src/auth/ProtectedRoute.tsx` — role-gated route wrapper
- `services/web/src/pages/SchedulePage.tsx` — main dispatcher view
- `services/web/src/pages/SetupPage.tsx` — schools/quals/drivers/vehicles create+list
- `services/web/src/pages/DriverPage.tsx` — Phase 4 driver view (`/driver`): run cards, status buttons, read-aloud
- `services/web/src/layout/AppLayout.tsx` — header, role-conditional nav (Schedule/Setup for dispatcher/admin, My Runs for driver), logout
- `services/web/src/App.tsx` — routes + `RoleHome` (role-aware `/` redirect: driver → `/driver`, else → `/schedule`)
- `services/api/Dockerfile`, `services/web/Dockerfile`, `services/web/nginx.conf`, `docker-compose.yml`, `.dockerignore` (root, api's build context) / `services/web/.dockerignore`
- `docs/architecture.md` — system diagram + phase table + known gaps — **keep updated per PR**
- `docs/adr/0001`–`0008` — architecture decision records

## Exact next step (as of this checkpoint)

Phase 4 MVP (PR #13) and auth hardening (PR #14, both ADR 0006
follow-ups — login rate limiting, logout revocation) are both
**merged**, CI green on both, local `main` synced (commit `86cd3a3`).

**No known gap is currently blocking further work.** What's left in
`docs/architecture.md`'s gap list is either genuinely deferred to a
later phase (student/stop entities — Phase 5; field trips/absences —
Phase 6) or an integrations boundary with nothing concrete to build
against yet (ADR 0007). Reasonable next candidates, roughly in order
of how directly they extend what's just shipped:

- Phase 5 (parent/student app) — the next actual phase in the roadmap,
  needs its own scoping pass the way this session did for Phase 3 and
  Phase 4 (`EnterPlanMode`, an Explore pass over existing patterns,
  then a scoped-first-slice plan) before any code — this is the most
  substantial of the candidates, involving new domain entities
  (Student/Guardian, spec §3) that don't exist yet.
- Phase 4 follow-ups the MVP intentionally left out (see ADR 0008 /
  architecture.md's Phase 4 row): absence reporting, GPS/live
  position (would need ADR 0007's "streamed telemetry" shape built for
  real), offline support.
- The one remaining minor, non-blocking polish item: `services/api`
  doesn't use the SQLAlchemy 2.0 mypy plugin, so ORM constructor
  kwargs (e.g. `Assignment(run_id=...)`) aren't strictly type-checked
  against column types — noticed once during earlier mypy work, not
  investigated further, genuinely low priority.

None of these were asked for — don't start one without checking
whether the user actually wants it over continuing toward Phase 5,
which is the natural next phase in the roadmap if no other direction
is given.

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
- `isd_api_dev.db` (default dev DB path) got wedged behind the
  "ghost process" gotcha above during the Phase 4 → auth-hardening
  session boundary — a stale uvicorn instance kept it locked
  (`rm`/`del` fails with "Device or resource busy") without being
  killable by any available tool. The auth-hardening verification pass
  used a throwaway `verify_dev.db` + port 8001 instead and cleaned
  both up after. If `isd_api_dev.db` is still locked when this file is
  next read, don't fight it — use a differently-named scratch DB file
  again rather than losing time on process archaeology. Whatever state
  `isd_api_dev.db` itself is in (Phase 3-era seed data, Phase 4's
  driver/crew/run seed, or untouched) should be treated as scratch,
  not a fixture to build on — reseed or reset as needed.
- `.claude/launch.json` (gitignored, not repo-tracked) has an
  `isd-web` entry pointing at `http://localhost:5173` for the Browser
  tool's `preview_start` — if a Vite dev server is already running on
  that port from a prior turn, `preview_start` attaches to it instead
  of starting a new one (`"url"` config, no `runtimeExecutable`).

## Memory system

Persistent cross-session memory lives at
`C:\Users\gmbug\.claude\projects\D--Projects-isd-bus-routing\memory\`
(`MEMORY.md` index + per-topic files) — that's a **different**,
complementary mechanism to this file: private to Claude, not
repo-tracked. This file is repo-tracked so it survives even without
access to that memory directory (a fresh branch, a different machine,
a clone). Keep both updated; they should never contradict each other.
