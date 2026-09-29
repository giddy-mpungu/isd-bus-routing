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

The same `docker-compose.prod.yml` stack *has* been run end to end on a
laptop, with migrations, production mode, and Caddy, through the local
demo overlay: see [docs/demo.md](demo.md). That run caught one real bug,
now fixed: the web image's healthcheck used `localhost`, which resolves
to IPv6 inside Alpine, while nginx listens only on IPv4, so a healthy
web container was reported unhealthy. What the demo doesn't exercise is
a real domain, Let's Encrypt, and an internet-facing host.

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

3. **Create the database secret file** (a Docker secret, not a plain
   environment variable — see the comment at the top of
   `docker-compose.prod.yml` for why):

   ```bash
   openssl rand -base64 32 | tr -d '\n' > secrets/postgres_password.txt
   chmod 600 secrets/postgres_password.txt
   ```

4. **Create the real secrets file:**

   ```bash
   cp .env.prod.example .env
   ```

   Fill in every value `.env.prod.example` marks as required —
   including `ISD_API_DATABASE_URL`, which must contain the *exact
   same* password as `secrets/postgres_password.txt` from step 3.
   Generate the JWT secret with:

   ```bash
   openssl rand -base64 48   # ISD_API_JWT_SECRET_KEY
   ```

   `docker-compose.prod.yml` deliberately fails to start (with a clear
   "set X in .env" error, via Compose's `${VAR:?message}` syntax)
   rather than silently falling back to an insecure default for any of
   these — that's intentional, not a bug to work around.

5. **Build and start everything:**

   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

   The first start issues a Let's Encrypt certificate for
   `CADDY_DOMAIN` automatically — watch for it:

   ```bash
   docker compose -f docker-compose.prod.yml logs -f caddy
   ```

6. **Run migrations** (not automatic on container start — see the
   comment in `services/api/Dockerfile` for why: concurrent replicas
   would race):

   ```bash
   docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
   ```

7. **Create the first administrator** (the same chicken-and-egg
   bootstrap script used in dev — see ADR 0006):

   ```bash
   docker compose -f docker-compose.prod.yml run --rm \
     -e ISD_API_BOOTSTRAP_EMAIL=you@yourdistrict.example.org \
     -e ISD_API_BOOTSTRAP_PASSWORD='choose-a-real-password' \
     -e ISD_API_BOOTSTRAP_NAME='Your Name' \
     api python scripts/bootstrap_admin.py
   ```

8. **Verify:**

   ```bash
   curl -sf https://bus.yourdistrict.example.org/api/health
   ```

   Then open `https://bus.yourdistrict.example.org` in a browser and
   log in with the account from step 7.

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

## Map tiles

The fleet map (Schedule page), the family "Locate bus" map and the
stops map (Setup) draw OpenStreetMap tiles in the viewer's browser. The
tile server receives each viewer's IP address and which map squares
they look at. For a family, that's roughly where their child's bus is.

- **Pilot / demo**: leave `MAP_TILE_URL` blank. The public OSM servers
  are free for light use under their
  [tile usage policy](https://operations.osmfoundation.org/policies/tiles/),
  which requires the attribution the app already shows. They aren't
  meant for heavy production traffic.
- **Go-live**: set `MAP_TILE_URL` (and `MAP_ATTRIBUTION`) in `.env` to a
  tile provider the district has a data agreement with, or to a
  self-hosted tile server, then rebuild the web image
  (`docker compose -f docker-compose.prod.yml up -d --build web`). The
  value is baked in at build time, like `PUBLIC_API_ORIGIN`.

The family map is approximate by design: the API rounds the bus position
to about 100 m, and that map won't zoom in past street level.

The web image's Content-Security-Policy allows tiles only from
`MAP_TILE_URL`'s host (see "Security headers" below), so a new tile
provider only needs that one value and a rebuild. Leaflet's `{s}`
subdomain placeholder becomes a `*.` wildcard, e.g.
`https://{s}.tiles.example.com/{z}/{x}/{y}.png` allows
`https://*.tiles.example.com`. A value that isn't an absolute http(s)
URL or a same-origin `/path` fails the image build.

## OpenRouteService key (optional)

`ISD_API_ORS_API_KEY` in `.env` turns on road-network deadhead times for
scheduling and turn-by-turn directions on the driver app. Without it the
scheduler uses straight-line estimates and the driver app shows the stop
order with a link to open each stop in the tablet's maps app. ORS's free
tier allows about 2,000 directions requests a day; directions are cached
for 10 minutes per run, so a fleet of a few dozen buses fits comfortably.
The key stays on the server; tablets never see it.

## Address lookup (US Census geocoder)

Transportation admins can look up student home addresses (Setup →
Schools & students → Home). The API sends only the address, over HTTPS,
to `https://geocoding.geo.census.gov` (free, no key, US addresses only).
The host needs outbound HTTPS to that domain. If it's blocked, lookups
fail with a clear message and admins can still place homes on the map.

Addresses are personal data: only transportation admins can see them,
the audit trail records that a home changed but not the address, and
backups contain them like any other student record.

## Security headers

Every response carries a strict set of browser security headers. Most
are set once in the `Caddyfile`, for the SPA and the api alike:

| Header | Value | Why |
| --- | --- | --- |
| `Strict-Transport-Security` | `max-age=31536000` | HTTPS only; never sent over plain HTTP (the local demo). No `includeSubDomains`, so this host doesn't force HTTPS on the rest of the district's domain. Add it yourself if you want that. |
| `X-Content-Type-Options` | `nosniff` | |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Cross-origin requests see only the origin. OpenStreetMap's tile policy needs a Referer, and the origin satisfies it. |
| `Permissions-Policy` | `geolocation=(self)`, and camera, microphone, payment, USB etc. off | The driver app reports GPS; nothing else is needed. |
| `X-Frame-Options` | `DENY` | For browsers without CSP `frame-ancestors`. |
| `Cross-Origin-Opener-Policy` | `same-origin` | |
| `Server` | removed | |

Content-Security-Policy differs by path:

- **api (`/api/*`)**, set by Caddy: `default-src 'none'; frame-ancestors 'none'`.
  The api returns only JSON, so nothing in a response may load, run or
  be framed. FastAPI's interactive `/docs` page won't render behind it
  (it didn't work behind the `/api` prefix before either).
- **SPA (everything else)**, sent by the web container's nginx. It's
  generated during the image build by `services/web/scripts/csp.mjs`
  from the same build args the bundle uses, so it always allows exactly
  the api and tile origins that build talks to:

  ```text
  default-src 'self'; script-src 'self'; style-src 'self';
  img-src 'self' data: <MAP_TILE_URL's origin>; connect-src 'self' <PUBLIC_API_ORIGIN's origin>;
  object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
  ```

  No `'unsafe-inline'` anywhere: Leaflet and React set styles through
  the CSSOM, which CSP doesn't restrict. When `PUBLIC_API_ORIGIN` is on
  the same origin as the site, as the Caddy setup requires, it's
  already covered by `'self'`.

To check a deployment, run
`curl -sI https://bus.yourdistrict.example.org/` and
`curl -sI https://bus.yourdistrict.example.org/api/health` and compare
the headers against the table above. In the browser, the console should
show no `Content Security Policy` errors on the Schedule page, the
driver's "My day" or the family page. A violation there means a new
external resource was added without updating `csp.mjs`.

## Security checklist before go-live

- [ ] `.env` contains real, unique, generated secrets (never the
      `.env.prod.example` placeholders) and is not committed anywhere.
- [ ] `secrets/postgres_password.txt` exists, is `chmod 600`, is not
      committed, and its contents match the password inside
      `ISD_API_DATABASE_URL` in `.env`.
- [ ] `ISD_API_CORS_ALLOWED_ORIGINS` is the exact real public origin,
      not a wildcard, not a dev origin.
- [ ] The host's firewall allows only 80/443 (and SSH for
      administration) — Postgres is not published to the host in
      `docker-compose.prod.yml` and should stay that way.
- [ ] Off-host backups are scheduled and a restore has actually been
      tested once against a throwaway environment.
- [ ] `ISD_API_POSITION_HISTORY_DAYS` matches the district's records
      policy for vehicle location data (default 30 days; see ADR 0009's
      addendum). Report CSVs contain driver names, absences and
      locations: treat downloaded files like any other staff record.
- [ ] `MAP_TILE_URL` points at a tile server the district has approved
      (see "Map tiles" above), not the public OpenStreetMap servers.
- [ ] The security headers are actually served (see "Security headers"
      above): `curl -sI` on `/` and `/api/health` both show
      `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
      `Referrer-Policy`, `Permissions-Policy` and a
      `Content-Security-Policy`, and the fleet map's tiles load with no
      CSP errors in the browser console. If you replaced Caddy with your
      own reverse proxy, it must set these headers itself; only the
      SPA's CSP comes from the web image.
- [ ] The first administrator's password is a real, unique password,
      not the placeholder from this document.
- [ ] `docs/adr/0006-persistence-and-rbac.md`'s open follow-ups
      (DB-level append-only enforcement on the audit log; rate
      limiting is shared per-process only and won't work correctly
      behind a multi-worker or multi-replica deployment) are read and,
      if this deployment runs more than one API replica, addressed
      first — see that ADR for exactly what's still missing.
