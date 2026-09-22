# ADR 0006: Persistence and RBAC design (Phase 2)

Status: Accepted
Date: 2026-08-27

## Context

Phase 2's job (per the root README's phase table) is to give the
Phase 1 solver real persistence and put it behind an authenticated,
role-scoped API, with an audit trail — proving the solver works as a
service, not just a library.

## Decisions

**Dialect-portable schema, PostGIS deferred.** ADR 0003 named
PostgreSQL + PostGIS as the production data layer. This development
environment has no PostgreSQL server available (sandboxed, no way to
install/run one here), so all models use plain, dialect-portable
SQLAlchemy types (`Float` lat/lon columns, not PostGIS `geography`;
`JSON`, not `JSONB`; `Enum(..., native_enum=False)`, not a native
Postgres enum type) so the exact same schema and test suite run
against SQLite here and against PostgreSQL in production without
divergent code paths. Real geospatial querying (stop clustering,
proximity search) is deferred until PostGIS is actually available to
develop against — tracked in docs/domain-model.md's "Not yet
implemented" list.

**Auth: JWT + bcrypt directly, not passlib.** passlib's bcrypt backend
has a known compatibility break with bcrypt>=4.1 (it probes for a
`__about__.__version__` attribute recent bcrypt releases no longer
ship). Calling the `bcrypt` library directly avoids depending on an
unmaintained compatibility shim for a security-critical code path.

**RBAC is enforced per-endpoint, not per-role blanket.** Each router
declares the exact role set spec section 17 grants for that specific
action (e.g. `POST /schools` is transportation_admin only; `GET
/schools` is any authenticated role) rather than one global "is this
role allowed in this router" check — different actions within the
same resource legitimately need different role sets, and a blanket
check would either over- or under-grant.

**Student/Parent roles exist, their data model doesn't yet.** `Role`
includes `student` and `parent` per spec section 17, but there is no
Student/Guardian persistence yet (spec section 3, still on the "Not
yet implemented" list). Endpoints for those two roles are
intentionally absent rather than stubbed — a stub that returns empty
data is worse than no endpoint, since it looks like a working feature.

**Audit log is insert-only by convention, not by DB grant.** A
security-hardened deployment should additionally enforce this with a
DB-level trigger or a restricted application role without UPDATE/
DELETE grants on `audit_log_entries` — not yet done, tracked below.

**Bootstrap script, not a hardcoded first admin.** `POST /users`
requires an existing transportation_admin, which is a chicken-and-egg
problem for the very first user. `scripts/bootstrap_admin.py` reads
credentials from the environment and refuses to run if any user
already exists — so it can create exactly one first admin and can't be
reused as a backdoor.

## Update (PR #38): PostgreSQL now verified in CI, PostGIS still deferred

The "dialect-portable schema" decision above was written when this
development environment had no PostgreSQL server to test against at
all. That's no longer the blocker it was: `.github/workflows/ci.yml`'s
`api-postgres` job runs every Alembic migration (up, down, up again,
drift-checked) and the full application test suite against a real
`postgres:16` server on every push. `docker-compose.prod.yml` /
`docs/deployment.md` are the first production-shaped deployment
artifacts. PostGIS itself remains deferred exactly as this ADR
originally decided — no geospatial column type is used yet, so plain
`postgres:16` is what CI and the deployment compose file both run.

## Consequences / follow-ups not yet done

- DB-level enforcement that `audit_log_entries` is truly append-only
  (trigger or restricted grant) — currently relies on application code
  discipline only.
- PostGIS migration once there's a real PostgreSQL environment to
  develop against.
- ~~Rate limiting / login throttling on `POST /auth/login`~~ **Closed.**
  An in-memory, per-process fixed-window limiter (`security.LoginRateLimiter`)
  rejects a client IP's login attempts beyond a configurable threshold
  with 429. Deliberately in-process rather than shared storage — the
  current deployment (`docker-compose.yml`) is a single uvicorn
  process with no reverse proxy in front of it; a future multi-worker
  or behind-a-proxy deployment would need shared storage and
  `X-Forwarded-For` handling instead.
- ~~Refresh tokens / token revocation~~ **Revocation closed, refresh
  tokens deliberately not built.** Every issued JWT (bearer and
  session) now carries a `jti` claim; `POST /auth/logout` revokes it
  server-side via a `revoked_tokens` denylist table (`security.revoke_token`),
  checked on every request in `get_current_user` — closes the actual
  gap (a captured token staying valid after "logout" until its natural
  expiry). A separate short-lived-access + long-lived-refresh token
  *pair* was considered and rejected as redundant: the Phase 3 sliding
  session cookie (renewed on every authenticated request, capped by an
  absolute `session_absolute_max_hours`) already does what a refresh
  token would for the browser session; the bearer-token flow is for
  scripts/API clients, where a fixed expiry needing re-login is the
  simpler, expected behavior.
