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
| 3 | Dispatcher console (web) | not started |
| 4 | Driver app | not started |
| 5 | Parent/student app + demand-based routing | not started |
| 6 | Dynamic rerouting, substitute coverage, historical learning | not started |

See `docs/adr/` for the reasoning behind irreversible decisions
(stack, service boundaries, constraint modeling, explainability/audit
approach). Read these before making changes that touch them.

## Repository layout

```
docs/
  adr/                 Architecture Decision Records
  domain-model.md       Entity definitions and invariants
services/
  solver/               Python/OR-Tools CP-SAT scheduling & routing engine
  api/                   FastAPI persistence + RBAC + HTTP layer (Phase 2)
```

## Stack

- Solver: Python + Google OR-Tools (CP-SAT)
- API: Python + FastAPI, SQLAlchemy 2.0, Alembic migrations
- Data: SQLite (dev/test, used in this environment), PostgreSQL + PostGIS (production target — see ADR 0006)
- Dispatcher console (Phase 3+): React + TypeScript
- Deployment: containerized, cloud-agnostic

## Getting started (solver)

```bash
cd services/solver
pip install -e ".[dev]"
pytest                                  # runs tests, verbose, with solver log output
python examples/run_worked_example.py   # runs the spec section 5 example and prints the schedule + explanations
```

## Getting started (api)

```bash
cd services/api
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
