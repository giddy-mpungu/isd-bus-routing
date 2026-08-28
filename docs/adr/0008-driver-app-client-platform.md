# ADR 0008: Driver app client platform

Status: Accepted
Date: 2026-08-28

## Context

ADR 0003 deferred Phase 4 (driver app)'s client-platform choice
explicitly: "Mobile clients (Phase 4+): decision deferred — evaluate
React Native vs. Flutter against the driver-app's 'large controls,
minimal typing, restricted while moving' requirements (spec §9) once
we're building it." Phase 4 is now being built, so this ADR settles
that decision rather than leaving it as an open note in ADR 0003.

## Decision

**Build the driver app as a responsive web app in the existing
`services/web` React + TypeScript + Vite stack (spec §9), not as a
new native mobile app.** New route (`/driver`), same build/lint/test
toolchain, same CI job, same deployment (Docker + nginx, ADR from the
Phase 3 Docker work) as the dispatcher console — no new service, no
new toolchain, no app-store distribution pipeline.

Reasoning:

- Spec §9's actual requirements — "large controls, minimal typing,
  audible instructions, restricted while moving" — describe a UI
  design constraint, not a platform requirement. A responsive web page
  satisfies "large controls" and "minimal typing" as directly as a
  native app would; "audible instructions" is met with the browser's
  native `SpeechSynthesis` API, no native SDK needed.
- One toolchain, one CI pattern, one deployment story. React
  Native and Flutter would each add a second build pipeline, a second
  test runner, and (for real distribution) an app-store review
  process — real ongoing cost for a solo-maintained project, not a
  one-time cost.
- **This does not foreclose a native app later.** `services/api`
  already runs two independent, parallel auth mechanisms (ADR 0006):
  an httpOnly `SameSite=Lax` session cookie for browser clients, and a
  stateless bearer-token JWT via the `Authorization` header, already
  used today by tests/Swagger/API scripts. A future React Native or
  Flutter client would authenticate via that same bearer-token flow —
  it needs zero backend changes, since the API was never cookie-only
  to begin with. Choosing "web app now" is a client-side decision that
  doesn't narrow future client-platform options.

Alternatives considered and why deferred (not rejected outright):

- **React Native**: real advantage is native device APIs (camera,
  push notifications, background GPS) if a later slice needs them —
  none of Phase 4's first slice (view own runs, mark status) needs
  any. Revisit if a future slice specifically needs a capability the
  browser can't provide (e.g. background location for live GPS
  tracking, spec §19's GPS/AVL integration, ADR 0007).
- **Flutter**: same reasoning as React Native, plus zero code/tooling
  reuse with the existing TypeScript stack (a new language, Dart, for
  a one-person team to maintain) — a strictly weaker case than React
  Native for this project specifically.

## Consequences

- Phase 4's driver-facing UI lives in `services/web/src/pages/DriverPage.tsx`
  alongside the dispatcher console, not a new package.
- If a future need genuinely requires native device APIs, that's a new
  ADR superseding this one for that specific capability — not a reason
  to have built native from the start when nothing in this slice
  needed it.
- `docs/architecture.md`'s Phase 4 row updates from "Not started" to
  reflect the shipped slice; the system-context diagram's `DriverApp`
  node's `(tablet, Phase 4+)` label still holds — a responsive web app
  runs fine on a tablet browser.
