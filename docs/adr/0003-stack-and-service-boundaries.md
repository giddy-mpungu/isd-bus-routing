# ADR 0003: Stack and service boundaries

Status: Accepted
Date: 2026-08-25

## Context

Startup with a small team, security-by-design and scalability
requirements, and an eventual need for multiple client apps (web
dispatcher console, driver tablet app, parent/student app).

## Decision

- **Solver service**: Python + Google OR-Tools (CP-SAT). Chosen over a
  hand-written heuristic solver because CP-SAT gives us a proven,
  actively-maintained constraint solver with native support for
  interval/no-overlap scheduling (needed for spec §5) rather than a
  bespoke implementation we would have to independently validate for
  correctness.
- **API/backend** (Phase 2+): Python + FastAPI, same language as the
  solver to minimize context-switching for a small team and share
  Pydantic domain types between the two.
- **Data layer** (Phase 2+): PostgreSQL + PostGIS for geospatial
  queries (stop generation, road-network work).
- **Web client** (Phase 3+): React + TypeScript.
- **Mobile clients** (Phase 4+): decision deferred — evaluate React
  Native vs. Flutter against the driver-app's "large controls, minimal
  typing, restricted while moving" requirements (spec §9) once we're
  building it.
- **Deployment**: containerized (Docker) from day one; avoid
  cloud-provider-specific managed services in the core solver/API so
  the system is not locked to one vendor. Cloud target (Azure/AWS/GCP)
  is a later, reversible decision — infra-as-code should make the
  choice swappable.

## Consequences

- The solver is usable standalone (CLI/library) before any API or UI
  exists, which is what makes an incremental, testable Phase 1
  possible.
- Because solver and API share a language, we can share validated
  Pydantic models for the domain entities instead of maintaining a
  second schema in another language.
