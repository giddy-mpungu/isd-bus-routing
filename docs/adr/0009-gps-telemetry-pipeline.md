# ADR 0009: GPS telemetry pipeline (spec §9/§18)

Status: Accepted
Date: 2026-09-14

## Context

Spec §9 (real-time navigation and operations) and §18 (parent/student
app) both depend on live vehicle position: dispatchers need a "GPS
fleet view" (§17), and families need "approximate bus location" and
ETA for their own child's ride. Before scoping the feature, two things
had to be decided: where position data comes from (hardware/vendor),
and how it moves from the driver's vehicle to everyone else's screen
(transport mechanism). REBOOT.md flagged both as likely needing a
real vendor/hardware decision, to be surfaced to the user rather than
assumed — the investigation below resolves both without one, because
ADR 0008 already answered the hardware question as a side effect of
an earlier decision.

## Decision

**Position source: the browser Geolocation API, running in the
existing `/driver` page on the same district-issued tablet ADR 0008
already put there.** No new hardware, no GPS/AVL vendor, no cost. This
isn't a new decision so much as a consequence of ADR 0008: once the
driver app is a web app on a tablet the driver already carries, that
tablet's own location sensor is the natural source — a dedicated GPS
unit per bus would be a second system to buy, install, and maintain
for data the tablet already has.

Real limitation, named rather than glossed over: browser geolocation
in a foreground tab does not track in the background if the driver
app is minimized or the screen locks (ADR 0008 flagged exactly this
gap when it deferred native apps). MVP scope assumes the driver app
stays open and foregrounded while driving — reasonable for a
dashboard-mounted tablet used as the drivers's assignment/navigation
display, but a real constraint, not a hidden one. Background tracking
would need a native wrapper or a dedicated GPS unit; revisit only if
this MVP assumption turns out false in practice.

**Transport: polling, not push (WebSockets/SSE).** The driver's tablet
`PUT`s its position periodically (target: every 15-30s while an
assignment is in progress); dispatcher and family views `GET` current
positions on their own refresh interval. No new infrastructure
(message broker, WebSocket-capable deployment topology) beyond what
`docker-compose`/nginx already run. Chosen over push because nothing
in this project's current deployment model (single API instance, ADR
0003) needs push's main advantage — sub-second latency — for a school
bus's position, where 15-30 seconds of staleness is operationally
irrelevant. Revisit if either a genuinely low-latency use case
appears, or a multi-instance deployment makes polling's per-poll DB
load a real cost (neither is true today).

**Storage: latest position only, overwritten in place — no breadcrumb
trail.** One `VehiclePosition` row per crew (crews are already scoped
to one service_date), updated on every ping rather than appended.
Spec §20 (historical data/learning) could eventually want a full
track log for post-hoc route-deviation analysis, but nothing consumes
that yet — building it now would be speculative storage with no
reader, against this project's own no-speculative-abstraction
practice. Named as a explicit, deliberate follow-up if/when §20 work
actually needs it.

## Consequences

- `VehiclePosition` (`services/api/src/isd_api/models.py`) is a thin
  table: `crew_id` (unique), lat/lon, `recorded_at`. No history, no
  separate GPS/AVL integration boundary in ADR 0007's sense — this is
  first-party data the driver's own tablet produces, not an external
  system being integrated.
- `docs/architecture.md`'s Phase 6 row and system-context diagram
  should note this closes spec §9/§18's live-position piece; the
  driver-app/incident-reporting/dispatch-messaging parts of §9 and the
  delay/substitution/route-change notification parts of §18 remain
  explicitly unbuilt follow-ups, not silently implied by this ADR.
- If a future slice needs true real-time push (e.g. sub-minute alerts
  a family shouldn't have to poll for), that's a new ADR superseding
  the transport half of this one — not a reason to have built
  WebSocket infrastructure now for a need that doesn't exist yet.

## Addendum (2026-09-28, PR #55): position history

The "no history" half of this decision is reversed; the transport half
(the tablet's browser Geolocation API, no push) stands. Since PR #56 the
tablet uses one continuous `watchPosition` feed instead of a 20-second
`getCurrentPosition` poll: the same fixes tell whether the bus is moving
(the in-motion lockout), and reports to the server are still sent at
most every 20 seconds.

§20's "follow-up if/when §20 work actually needs it" arrived with Phase
2.5: on-time reporting, a bus's track on the fleet map (§9 "route
progress"), and later route-deviation checks all need where a bus has
been, not just where it is now.

- Every `PUT /drivers/{id}/position` still updates `VehiclePosition`
  (latest, for the live view) and now also appends a `PositionSample`
  (`isd_api/position_history.py`). A repeated reading (same crew, same
  `recorded_at`, e.g. a retry) is stored once.
- **Retention**: samples older than `ISD_API_POSITION_HISTORY_DAYS`
  (default 30) are deleted, on the write path at most once an hour per
  process. A track shows where a bus full of students was, so it's kept
  only as long as operations need it; a district can shorten it, or
  lengthen it if its records policy requires.
- Reads are dispatcher/admin only:
  `GET /schedule/{date}/fleet-positions/{crew_id}/track` and the
  positions report (`GET /reports/positions`, 7 days at a time).
- Still not built: route-deviation detection, which needs a planned
  route geometry (Phase 3).
