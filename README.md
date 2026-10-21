# isd-bus-routing

School district transportation routing, scheduling, dispatch, and
decision-support system. Specialized multi-objective Vehicle Routing
and Scheduling Problem (VRP) solver for K-12 transportation, wrapped
by role-scoped applications for dispatchers, drivers, parents/students,
school admins, and transportation admins.

Author: Gideon Mpungu

## Why this exists

Commercial K-12 routing software optimizes for the mathematically
shortest route. This system treats school transportation as a
continuously changing resource-allocation problem — students, stops,
schools, drivers, vehicles, time, geography, safety, and daily demand —
and produces a plan that is safe, feasible, explainable, and
resource-efficient, with mandatory human override at every level.

Full requirements: see `docs/domain-model.md` and the source
specification this project is built from (kept out of version control
if it contains district-identifying details — check before committing).

## Methodology

This project is built in phases, each a runnable, testable increment —
not a big-bang build of the full spec:

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Domain model + Architecture Decision Records | ✅ done |
| 1 | Headless solver MVP: multi-school crew scheduling (spec §5) | ✅ done, hardened (capacity, real-routing estimator, observability) |
| 2 | Persistence + RBAC skeleton | ✅ done — see services/api |
| 3 | Dispatcher console (web) | 🚧 MVP shipped — login + schedule view, see services/web |
| 4 | Driver app | not started |
| 5 | Parent/student app + demand-based routing | not started |
| 6 | Dynamic rerouting, substitute coverage, historical learning | not started |

See `docs/adr/` for the reasoning behind irreversible decisions
(stack, service boundaries, constraint modeling, explainability/audit
approach). Read these before making changes that touch them.

See `docs/architecture.md` for the system-context diagram, the full
spec-section-to-phase mapping, and known gaps to close before the next
phase starts.

## Repository layout

```
docs/
  adr/                 Architecture Decision Records
  domain-model.md       Entity definitions and invariants
services/
  solver/               Python/OR-Tools CP-SAT scheduling & routing engine
  api/                   FastAPI persistence + RBAC + HTTP layer (Phase 2)
  web/                   React/TypeScript dispatcher console (Phase 3, MVP)
```

## Stack

- Solver: Python + Google OR-Tools (CP-SAT)
- API: Python + FastAPI, SQLAlchemy 2.0, Alembic migrations
- Data: SQLite (dev/test, used in this environment), PostgreSQL + PostGIS (production target — see ADR 0006)
- Dispatcher console (Phase 3, MVP shipped): React + TypeScript + Vite, oxlint + Prettier, Vitest + React Testing Library
- Deployment: containerized (Dockerfiles for api + web, `docker-compose.yml` for local orchestration), cloud-agnostic — see "Getting started (Docker)" below, and `docs/deployment.md` for a real production deployment

## Getting started (solver)

```bash
cd services/solver
pip install -e ".[dev]"
pytest                                  # runs tests, verbose, with solver log output
python examples/run_worked_example.py   # runs the spec section 5 example and prints the schedule + explanations
```

## Getting started (api)

```bash
# api imports the solver directly and doesn't declare it as a
# dependency (see the comment in services/api/pyproject.toml) — it
# must be installed first.
cd services/solver && pip install -e .
cd ../api
pip install -e ".[dev]"

# First-time setup: create the DB schema.
alembic upgrade head

# Create the first admin user (reads from env, refuses if any user exists).
ISD_API_BOOTSTRAP_EMAIL=you@example.org \
ISD_API_BOOTSTRAP_PASSWORD='choose-a-real-password' \
ISD_API_BOOTSTRAP_NAME='Your Name' \
python scripts/bootstrap_admin.py

pytest              # runs the full RBAC + persistence + end-to-end schedule test suite
uvicorn isd_api.main:app --reload    # http://127.0.0.1:8000/docs for interactive API docs
```

By default this runs against a local SQLite file (`isd_api_dev.db`) —
fine for development. For anything beyond that, set
`ISD_API_DATABASE_URL` to a real PostgreSQL connection string and set
`ISD_API_ENVIRONMENT=production` with a real `ISD_API_JWT_SECRET_KEY`
(the app refuses to start in production with the default dev secret).

## Getting started (web)

The dispatcher console (Phase 3 MVP: log in, view/run a date's
schedule, lock/unlock or delete an assignment — see
`docs/architecture.md` for what's in and out of scope for this slice).
Needs the api running first (previous section) — the dev server is
configured to talk to it at `http://localhost:8000`.

```bash
cd services/web
npm install
npm run dev     # http://localhost:5173
```

Log in with any `dispatcher` or `transportation_admin` user created
via `scripts/bootstrap_admin.py` or `POST /users`. Sessions use an
httpOnly cookie (never touched by this frontend's own code — see
`isd_api.security`) with a sliding 30-minute inactivity timeout and a
12-hour absolute cap, so a page refresh doesn't require logging in
again but leaving the tab idle eventually does.

## Getting started (Docker)

Runs api + web together via `docker-compose.yml` at the repo root —
useful for a closer-to-real check than the dev servers above, not a
production deployment manifest (see the comments in
`docker-compose.yml` and `services/api/Dockerfile` for why: SQLite,
the insecure default JWT secret, and `ISD_API_ENVIRONMENT=dev` are all
dev-only defaults a real deployment must override explicitly).

```bash
docker compose up -d --build
# api:  http://localhost:8000/docs
# web:  http://localhost:8080

# One-time: create the first admin user inside the running api container.
docker compose exec \
  -e ISD_API_BOOTSTRAP_EMAIL=you@example.org \
  -e ISD_API_BOOTSTRAP_PASSWORD='choose-a-real-password' \
  -e ISD_API_BOOTSTRAP_NAME='Your Name' \
  api python scripts/bootstrap_admin.py

docker compose down -v   # stop and remove the SQLite volume too
```

Migrations are **not** run automatically on container start (multiple
replicas would race to migrate concurrently) — run them as a one-off:
`docker compose run --rm api alembic upgrade head`.

## Local demo / beta testing

`scripts\demo.cmd up` runs the full production stack on your own
computer with a fictional demo district and one login per role;
`scripts\demo.cmd share` adds a free temporary HTTPS link for testers.
See `docs/demo.md`.

To install it on another Windows PC for people on that PC's Wi-Fi, clone the
repository there and double-click `deploy.cmd`: it installs Docker Desktop if
needed, builds and starts everything over HTTPS, and loads the same fictional
district. See `docs/home-install.md`.

## Production deployment

`docker-compose.prod.yml` (PostgreSQL + Caddy for automatic HTTPS) is
a separate manifest for actually deploying this somewhere real — see
`docs/deployment.md` for the full runbook (provisioning, first-time
setup, backups, updates, rollback). Every Alembic migration and the
full test suite are verified against real PostgreSQL in CI
(`api-postgres` job), not just SQLite.

## Development

Each service is linted and type-checked independently (they're
separate installable packages — see ADR 0003). Run from inside
`services/solver` or `services/api`:

```bash
ruff check .        # lint
ruff check . --fix  # lint, autofixing what's safe to autofix
ruff format .        # format
mypy                 # type-check the package source (src/)
pytest               # run that service's test suite
```

`services/web` uses the JS-ecosystem equivalents — run from inside it:

```bash
npm run lint          # oxlint
npm run format         # prettier --write
npm run format:check   # prettier --check
npm run build          # tsc -b && vite build (type-checks + bundles)
npm run test           # vitest run
```

The web app aims for WCAG 2.1 AA (the ADA Title II level). Each page
test checks every state it reaches with axe-core
(`src/test/axe.ts`), so a new page test should keep the same
`afterEach` hook. Colour contrast can't be measured in jsdom; check it
in a real browser with axe (or the browser's own accessibility tools)
when changing colours.

The family, driver and sign-in screens are translated (Spanish so far);
a new phrase goes in each `src/i18n/<language>.ts` or the build fails.
See `docs/translation.md`.

CI (`.github/workflows/ci.yml`) runs all of this for all three
services on every PR (and on demand) — run it locally before pushing so
CI is confirmation, not discovery. Merging needs a green PR, so `main`
isn't tested again on push: that keeps within GitHub's free 2,000
minutes a month for a private repository.

End-to-end tests (`e2e/`, Playwright) drive the whole system in a real
browser. Fresh seeded API + web rounds, as every role, run on every PR.
A fresh install that follows `docs/deployment.md` step by step, and the
outside systems (single sign-on through a real Keycloak, the SIS roster
sync, the worker's bus-time emails, directions and address lookups
against stand-ins), run in
`.github/workflows/e2e-heavy.yml`: on a PR that touches what they test,
every Sunday, and on demand. See `e2e/README.md` to run them locally
(`node e2e/scripts/seeded-rounds.mjs --rounds 1`).

## Non-negotiables (carried from spec)

- Hard constraints (capacity, qualification, legal time windows,
  overlapping assignments) are **never** relaxed to satisfy a soft
  objective.
- Every non-trivial assignment must be able to produce a human-readable
  explanation (spec §21).
- Driver-hour/break rules are configured per-district, never hardcoded
  as an assumed legal figure — this codebase does not encode specific
  federal/state driver-hour law.
- No student, driver, or family PII beyond what's operationally
  necessary is stored (spec §13).
