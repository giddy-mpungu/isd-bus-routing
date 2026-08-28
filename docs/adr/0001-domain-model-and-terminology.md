# ADR 0001: Domain model and terminology

Status: Accepted
Date: 2026-08-25

## Context

The spec uses several overlapping terms (route, run, trip, assignment)
loosely. Before writing any solver or persistence code, we need a
single, unambiguous vocabulary so that "route" in a driver-facing
screen and "route" in the solver's output mean the same thing.

## Decision

We adopt this vocabulary, used consistently across all services:

- **Student**: a person eligible for transportation, with an address,
  school assignment, and (per spec §4) a default ridership state.
- **Stop**: a physical location where one or more students board/alight.
- **School**: has one or more bell-time windows (AM arrival, PM
  dismissal) that runs must satisfy.
- **Run**: a single ordered sequence of stops serving one school for
  one direction (AM or PM) on one service day — the smallest unit the
  solver schedules. This is what commercial systems often call a
  "route," but we reserve "route" for the higher-level concept below.
- **Route**: the *permanent template* a run is generated from — the
  standing stop sequence and school assignment that exists across
  service days, independent of who drives it today (spec §11's
  "Permanent Assignment").
- **Crew**: a (Driver, Vehicle) pairing considered as a unit for a
  given assignment. Drivers and vehicles remain independently modeled
  resources (spec §13.2) — a crew is a scheduling-time pairing, not a
  persistent entity.
- **Assignment**: the mapping of a Crew to one or more Runs/Trips for
  a specific service day — spec §11's "Daily Operational Assignment."
- **Trip**: a non-recurring transportation job (field trip, athletic
  trip, shuttle) scheduled through the same engine as Runs (spec §12).
- **Job**: the general term covering both Run-instances and Trips when
  we mean "anything the scheduler can assign to a Crew."

## Consequences

- Solver code operates on **Jobs** and **Crews**, not on "routes" —
  avoids the route/run ambiguity in scheduling logic.
- Persistence layer (Phase 2) will have separate `route` (template)
  and `run` (dated instance) tables from the start, so permanent route
  ownership (spec §22, point 9) is representable without a migration.
