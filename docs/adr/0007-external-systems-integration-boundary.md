# ADR 0007: External systems integration boundary

Status: Accepted
Date: 2026-08-28

## Context

Spec §19 lists nine district systems this software should integrate
with rather than duplicate — SIS, HR, employee absence, SSO/identity,
fleet maintenance, GPS/AVL, routing/GIS, bell schedules, and
tablet/device infrastructure — and states the requirement plainly:
"the architecture should establish an authoritative data source for
each major entity." No such decision exists yet anywhere in the
codebase; `docs/architecture.md` has flagged this as a known gap since
Phase 2 closed. This ADR makes that decision now, before Phase 4+ work
(driver app, GPS ingestion) or Phase 5 (student data from SIS) touches
any of these systems — the goal is to settle data ownership and
integration shape up front so integration code doesn't get bolted on
ad hoc, one vendor's SDK at a time, the way ADR 0003 already avoids
for cloud infrastructure.

This ADR decides ownership and integration *shape*. It does not build
any integration — no adapter code, no new schema, no new dependency is
added by this change. Each system is integrated for real only when a
phase actually needs it, against this decision.

## Decision

**Five integration shapes, not nine one-off decisions.** Grouping the
spec's nine systems by how they actually need to be integrated avoids
inventing a bespoke pattern per vendor:

1. **Federated identity** (SSO/IdP) — authentication is delegated
   entirely; this system trusts asserted identity claims and never
   stores a password for a federated user.
2. **Synced read-model** (SIS, HR, bell-schedule database) — the
   external system is the system of record; this system keeps a local
   cache tied to it by an external ID, refreshed on a pull or webhook
   trigger, never hand-edited for the synced fields.
3. **Synced operational status** (fleet maintenance, employee
   absence) — same shape as (2), but the synced field feeds a hard
   constraint directly (spec §2.1: unavailable vehicle, unavailable
   driver), so staleness has an operational safety cost a read-model
   cache doesn't — push/webhook is preferred over polling, and manual
   entry is the deliberate fallback until a real integration exists,
   never a silent skip of the check.
4. **Streamed telemetry** (GPS/AVL) — not an entity to sync; a
   continuous ingestion point (webhook or streaming) feeding live
   state, not a request/response API in the other four shapes.
5. **External compute, not owned data** (routing/GIS) — already
   decided in practice by ADR 0005/`docs/domain-model.md`: this system
   calls an external routing provider per request rather than owning
   road-network data. District-specific overrides (spec §8 — "this
   intersection is unsafe," "this lot isn't a valid turnaround") are
   the one piece of routing-relevant data this system *does* own,
   layered on top of the external provider's output, never merged into
   it.

**Per-system authoritative source, using those shapes:**

| System | Shape | Authoritative for | This system stays authoritative for |
|---|---|---|---|
| SIS | Synced read-model | Student identity, enrollment, school assignment, address | Stop assignment, ridership status (transportation-derived, spec §3/§4) |
| HR system | Synced read-model | Employment status, core personnel record | Transportation-specific `Driver` record (license/vehicle qualifications) — kept minimal per the README's PII non-negotiable, not a personnel duplicate |
| Employee absence system | Synced operational status | Whether a driver is unavailable today | The scheduling consequence of that unavailability (substitute ranking, spec §13) |
| District IdP / SSO | Federated identity | Authentication, base identity claims | RBAC role assignment (spec §17) — an IdP typically asserts identity/groups, not this system's specific operational roles, so role mapping stays a local decision even after SSO adoption |
| Fleet maintenance system | Synced operational status | Vehicle in-service/out-of-service state | See note below — not a schema gap today |
| GPS/AVL system | Streamed telemetry | Live vehicle position | Route/ETA computation derived from that position |
| Routing/GIS provider | External compute | Road network geometry, base travel time | District-specific safety overrides (spec §8) |
| School bell-schedule database | Synced read-model | Official bell times, if a district maintains this separately | The `Run` window actually used for scheduling — may equal the official bell time or be adjusted by transportation staff (spec §5 windows are operational, not necessarily identical to the bell) |
| Tablet/device infrastructure | Not a data-ownership question | Device provisioning/MDM is a deployment concern, not an entity sync — out of scope for this ADR |

**Fleet maintenance note:** this system doesn't need a new
`Vehicle.out_of_service` field today. A `Crew` (driver+vehicle pair)
only exists for a specific `service_date` (ADR 0006) — a vehicle that's
out of service simply has no `Crew` row created for that date, so the
solver never sees it as a candidate. That already satisfies spec
§2.1's "unavailable or out-of-service vehicle" hard constraint by
construction. A future fleet-maintenance integration would drive
*which vehicles get a Crew row created*, not add a new state field to
`Vehicle` itself.

**Integration code shape, when each is actually built:** each external
system gets one adapter behind an interface this system defines (not
the vendor's shape), living under `services/api/src/isd_api/integrations/`
when the first one is built — mirrors ADR 0003's "avoid cloud-provider
lock-in" reasoning applied to district vendors instead of cloud
providers, since a district's SIS/HR/fleet vendor is exactly the kind
of dependency this system shouldn't be hard-wired to. Until a district
provides a real system to integrate against, the adapter's only
implementation is manual entry through this system's own API — never a
stub that fakes sync data, which would look like a working integration
and isn't (same reasoning ADR 0006 already applied to the
student/parent endpoints).

## Consequences

- No code changes from this ADR. The next system actually integrated
  (most likely SIS, when Phase 5 starts student data) is the first
  real test of the adapter-interface pattern described above.
- **Update (Phase 6 GIS slice 1):** routing/GIS turned out to be the
  first system actually integrated, not SIS — `isd_solver.ors_deadhead_estimator`
  calls OpenRouteService for real road-network deadhead times, wired
  in by `services/api/src/isd_api/routers/schedule.py` when
  `ISD_API_ORS_API_KEY` is configured. It deliberately does **not**
  live under `services/api/src/isd_api/integrations/` as this ADR's
  "Integration code shape" section describes — the estimator is a
  pure, injectable function (`Callable[[Location, Location], int]`)
  with no DB/framework dependency, a solver-level abstraction the API
  layer only configures and wires, not a persisted external entity.
  That location (`services/solver`, alongside the existing
  `straight_line_deadhead_estimator`/`osrm_deadhead_estimator`) is the
  reasonable exception for any future integration that fits this same
  "stateless per-request compute" shape — the `integrations/` home
  described below remains right for the synced-entity and streamed-
  telemetry shapes (SIS, HR, GPS/AVL, etc.).
- `Driver`/`User`/`Vehicle`/`School` records created manually today
  (Phase 2's only mode) are NOT retroactively assumed to have a stable
  external ID — a future sync integration will need an explicit
  reconciliation step (match-by-name-and-confirm, most likely) for
  data that predates the integration, not an assumed clean 1:1 join.
- SSO federation is deferred, not scheduled to a phase — Phase 2's own
  email/password + JWT auth (ADR 0006) remains the system's auth for
  as long as no district IdP integration exists, and should not be
  treated as a stopgap that blocks security hardening (rate limiting,
  token revocation — ADR 0006's own follow-ups) in the meantime.
- **Update (PR #37): SIS is now the first synced-entity integration.**
  It follows the "integration code shape" above: a pure adapter under
  `services/api/src/isd_api/integrations/` (`oneroster.py`) behind
  reconciliation logic in the router. It is vendor-neutral on purpose --
  OneRoster CSV, not any one vendor's API -- and is real data intake, not
  a stub. The reconciliation step this ADR predicted for pre-integration
  data is `link_by_name`, and it is opt-in after a dry run, never assumed.
