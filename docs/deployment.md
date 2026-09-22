# Deployment runbook

Status: prepared, not yet used against a real host. This document,
`docker-compose.prod.yml`, `Caddyfile`, and `.env.prod.example` are the
audit's item 5 — "get this deployable" — done as *preparation*, per an
explicit choice: build everything a deployment needs without picking a
host, so a host decision later is a copy-paste job, not a design
exercise. See `docs/REBOOT.md` for that decision record.

Nothing in this document has been run against a real server. Treat the
first real run of these steps as itself a test, and report back
anything that doesn't match.

## What this is (and isn't)

- **Is**: a self-hosted, single-server deployment — PostgreSQL, the API,
  the web build, and Caddy as a reverse proxy with automatic HTTPS, all
  via `docker-compose.prod.yml`. Reasonable for a pilot district or a
  small district running its own infrastructure.
- **Isn't**: a managed-cloud (AWS/GCP/Azure) or multi-server/
  high-availability deployment. ADR 0003 deliberately avoided
  cloud-provider lock-in in the core images, so a managed-cloud
  deployment later reuses the same Dockerfiles behind different
  orchestration (ECS/Cloud Run/etc.) — that's a separate, later
  decision, not blocked by anything here.
- **PostGIS**: still not used (ADR 0006 defers it — no geospatial
  querying exists yet). The `postgres:16` image here is plain
  PostgreSQL; switch to `postgis/postgis:16-3.4` only when a future
  phase actually adds PostGIS-typed columns.

## What's now proven, and what still isn't

- **Proven in CI** (`.github/workflows/ci.yml`'s `api-postgres` job):
  every Alembic migration applies cleanly to a real PostgreSQL 16
  server (up, down, up again, `alembic check` for drift), and the
  entire application test suite (RBAC, persistence, the full schedule
  flow) passes against that same real database, not just SQLite.
- **Not proven anywhere yet**: this exact `docker-compose.prod.yml` /
  `Caddyfile` pair running on a real host with a real domain, a real
  TLS certificate issuance, or a restore from a real backup. Budget
  time for a dry run against a throwaway host/subdomain before this is
  used for anything a district depends on.

## Prerequisites

- A Linux host (a small VPS is enough for a pilot — 2 vCPU / 4 GB RAM
  is a reasonable starting point) with Docker and the Docker Compose
  plugin installed, and ports 80 and 443 reachable from the internet.
- A domain name you control, with an A (and/or AAAA) record you can
  point at the host's IP.
- The ability to set environment variables / secrets on that host
  (shell access, or your host provider's secrets mechanism).

## First-time setup

1. **DNS first.** Point `bus.yourdistrict.example.org` (or your real
   subdomain) at the host's IP address, and confirm it resolves before
   continuing — Caddy's automatic certificate issuance will fail
   otherwise (and will keep retrying, so an unreachable domain looks
   like a hang here, not a clear error).

2. **Get the code onto the host** (clone the repo, or copy the
   built artifacts — either way you need `docker-compose.prod.yml`,
   `Caddyfile`, `.env.prod.example`, and the `services/` directory
   present, since the compose file builds the images from source).

3. **Create the real secrets file:**

   ```bash
   cp .env.prod.example .env
   ```

   Fill in every value `.env.prod.example` marks as required. Generate
   the two secrets with:

   ```bash
   openssl rand -base64 32   # POSTGRES_PASSWORD
   openssl rand -base64 48   # ISD_API_JWT_SECRET_KEY
   ```

   `docker-compose.prod.yml` deliberately fails to start (with a clear
   "set X in .env" error, via Compose's `${VAR:?message}` syntax)
   rather than silently falling back to an insecure default for any of
   these — that's intentional, not a bug to work around.

4. **Build and start everything:**

   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

   The first start issues a Let's Encrypt certificate for
   `CADDY_DOMAIN` automatically — watch for it:

   ```bash
   docker compose -f docker-compose.prod.yml logs -f caddy
   ```

5. **Run migrations** (not automatic on container start — see the
   comment in `services/api/Dockerfile` for why: concurrent replicas
   would race):

   ```bash
   docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
   ```

6. **Create the first administrator** (the same chicken-and-egg
   bootstrap script used in dev — see ADR 0006):

   ```bash
   docker compose -f docker-compose.prod.yml run --rm \
     -e ISD_API_BOOTSTRAP_EMAIL=you@yourdistrict.example.org \
     -e ISD_API_BOOTSTRAP_PASSWORD='choose-a-real-password' \
     -e ISD_API_BOOTSTRAP_NAME='Your Name' \
     api python scripts/bootstrap_admin.py
   ```

7. **Verify:**

   ```bash
   curl -sf https://bus.yourdistrict.example.org/api/health
   ```

   Then open `https://bus.yourdistrict.example.org` in a browser and
   log in with the account from step 6.

## Updating to a new version

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

Pull the new images/rebuild *before* migrating, so the old code never
runs against a newer schema than it expects. `alembic upgrade head` is
safe to run even when there's nothing new to apply.

## Rolling back

```bash
git checkout <previous-tag-or-commit>
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml run --rm api alembic downgrade <previous-revision>
```

The full migration chain, head to base and back to head again, has
been verified to run cleanly with no manual fixes (on SQLite; the
`api-postgres` CI job verifies each new migration the same way against
real PostgreSQL as it's added) — but a downgrade against real
production *data* (not an empty schema) has not been exercised. Take a
backup (below) immediately before rolling back a migration on data you
care about.

## Backups

PostgreSQL data lives in the `postgres-data` named volume. A logical
dump is the simplest reliable backup for this size of deployment:

```bash
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup-$(date +%F).sql
```

Restore into a fresh volume:

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_USER" "$POSTGRES_DB" < backup-2026-09-22.sql
```

Automate the dump on a schedule (e.g. a daily cron job calling the
`pg_dump` command above) and copy the resulting file off the host —
a backup that only ever lives on the same disk as the database it
backs up doesn't protect against that disk failing. This project does
not include that scheduling or off-host copy step yet; set it up
before this deployment holds any data a district depends on.

## Monitoring and logs

```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f caddy
docker compose -f docker-compose.prod.yml ps   # container health status
```

No centralized log aggregation or alerting is set up. For a pilot,
periodic manual log review is the starting point; a real district
deployment should ship these logs somewhere durable before go-live.

## Security checklist before go-live

- [ ] `.env` contains real, unique, generated secrets (never the
      `.env.prod.example` placeholders) and is not committed anywhere.
- [ ] `ISD_API_CORS_ALLOWED_ORIGINS` is the exact real public origin,
      not a wildcard, not a dev origin.
- [ ] The host's firewall allows only 80/443 (and SSH for
      administration) — Postgres is not published to the host in
      `docker-compose.prod.yml` and should stay that way.
- [ ] Off-host backups are scheduled and a restore has actually been
      tested once against a throwaway environment.
- [ ] The first administrator's password is a real, unique password,
      not the placeholder from this document.
- [ ] `docs/adr/0006-persistence-and-rbac.md`'s open follow-ups
      (DB-level append-only enforcement on the audit log; rate
      limiting is shared per-process only and won't work correctly
      behind a multi-worker or multi-replica deployment) are read and,
      if this deployment runs more than one API replica, addressed
      first — see that ADR for exactly what's still missing.
