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
docker compose -f docker-compose.prod.yml exec backup backup.sh pre-migration
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

The first line takes a backup before anything changes (see Backups).

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
backup (`backup.sh pre-migration`, below) immediately before rolling
back a migration on data you care about.

## Backups

The `backup` service (services/backup) backs the database up every night
at `BACKUP_TIME` (02:00, in `BACKUP_TZ`): a `pg_dump`, the newest 7 kept
on this server in the `backup-data` volume, and every one sent with
[restic](https://restic.net), **encrypted**, to `RESTIC_REPOSITORY` **off
this server**. restic keeps 7 daily, 4 weekly and 12 monthly snapshots
and deletes older ones. Every Sunday it also restores the latest backup
into a throwaway database to prove it works. These were the product
owner's choices (2026-10-04).

Set up before go-live:

1. Create a bucket with any S3-compatible provider (Backblaze B2, about
   $6 per TB a month; Cloudflare R2; AWS S3; Wasabi) and an access key
   limited to that bucket. Put `RESTIC_REPOSITORY`,
   `BACKUP_S3_ACCESS_KEY_ID` and `BACKUP_S3_SECRET_ACCESS_KEY` in `.env`
   (examples in `.env.prod.example`).
2. Generate the encryption password, and **store a copy in a password
   manager, off this server**. Without it, no backup can ever be read:

   ```bash
   openssl rand -hex 32 > secrets/restic_password.txt
   ```

3. Start it and take the first backup by hand:

   ```bash
   docker compose -f docker-compose.prod.yml up -d backup
   docker compose -f docker-compose.prod.yml exec backup backup.sh manual
   docker compose -f docker-compose.prod.yml exec backup check-restore.sh
   ```

Check on it any time:

```bash
docker compose -f docker-compose.prod.yml logs --tail 50 backup
docker compose -f docker-compose.prod.yml exec backup restic snapshots
```

**Restoring** replaces the whole database with a backup; everything since
is lost. Stop what writes to it first:

```bash
docker compose -f docker-compose.prod.yml stop api worker
docker compose -f docker-compose.prod.yml exec backup restic snapshots
docker compose -f docker-compose.prod.yml exec -e CONFIRM_RESTORE=isd_api backup restore.sh latest
docker compose -f docker-compose.prod.yml up -d api worker
```

(Use a snapshot id from `restic snapshots` instead of `latest` for an
older one; `CONFIRM_RESTORE` must be the database name, `POSTGRES_DB`.)
On a brand-new server, set up `.env`, the secrets and the stack first,
run `alembic upgrade head`, then restore.

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

## Background worker

`docker-compose.prod.yml` runs a `worker` service next to the api: the
same image and settings, no port. It sends families bus-time emails
(when today's pickup or drop-off moves 10+ minutes from the plan, from
05:30 district time) and will run the scheduled SIS sync. It needs email
configured to send anything. `docker compose -f docker-compose.prod.yml
logs worker` shows each pass that sent something and any failures. One
worker is enough; a second would never send duplicates, only waste work.

## SIS sync (optional)

The worker can read the student roster from the district's SIS every
night at `ISD_API_SIS_SYNC_TIME` (03:00 district time, after the 02:00
backup) through the **OneRoster 1.1 REST API**, which PowerSchool,
Infinite Campus, Skyward and hubs such as ClassLink offer. Ask the SIS
administrator for a OneRoster API connection with OAuth 2 client
credentials and read access to students; put the base URL (ending in
`/ims/oneroster/v1p1`), the token URL, the client ID and the secret in
`.env` (see `.env.prod.example`), then restart the api and worker.

Before the first sync, give each school its SIS ID (OneRoster org
`sourcedId`) under Setup, SIS import: a student only lands at a school
someone has mapped. Each sync applies new students and name, school and
grade changes on its own; possible duplicates, unmapped schools and
removal requests wait under Setup, SIS import, and transportation admins
are emailed (counts only, no names) when a sync fails or leaves something
waiting. "Sync now" there runs it straight away. Removals are never
applied automatically.

## Single sign-on (optional)

Staff can sign in with the district's own accounts through any OpenID
Connect provider (Microsoft Entra ID, Google Workspace, Okta, Keycloak,
...). Only people who already have an account here, with the same email,
get in; admins still add them in Users. Families keep passwords, and
passwords keep working for staff too.

1. Register an app with the provider: a confidential "web" client using
   the authorization code flow, redirect URI
   `https://bus.yourdistrict.example.org/api/auth/oidc/callback`, scopes
   `openid email profile`.
2. In `.env` set `ISD_API_OIDC_ISSUER` (single-tenant, e.g.
   `https://login.microsoftonline.com/<tenant-id>/v2.0` or
   `https://accounts.google.com`), `ISD_API_OIDC_CLIENT_ID`,
   `ISD_API_OIDC_CLIENT_SECRET` and `ISD_API_OIDC_REDIRECT_URI` (the same
   URI). The sign-in page then shows "Sign in with your district
   account" (`ISD_API_OIDC_LABEL` changes the wording).
3. Decide how far to trust the district's two-step check
   (`ISD_API_OIDC_TRUST_MFA`): `claim` (default) skips ours only when the
   ID token says MFA was used; `always` if the district enforces MFA for
   everyone signing in to this app but the token doesn't say so (common
   with Entra ID and Google); `never` always asks for ours too.

Use a single-tenant issuer: with a multi-tenant one, any organisation's
users could present an email that matches. Access logs record the
one-time authorization code in the callback URL; it's useless once
exchanged and, with PKCE, can't be redeemed without the browser's secret.

## Two-step sign-in

Transportation admins and dispatchers sign in with a password plus a
code from an authenticator app (Google or Microsoft Authenticator, a
password manager). They set it up the first time they sign in after
this is deployed; school admins and families may turn it on from
Account; drivers never use it.

`ISD_API_MFA_ENCRYPTION_KEY` is required: it encrypts each person's
authenticator secret. Generate it once and keep it with your other
secrets:

```bash
python -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Changing it later makes every stored secret unreadable, so everyone
would reset and set up two-step sign-in again. Which roles need it is
`ISD_API_MFA_REQUIRED_ROLES` (JSON list).

A lost phone: the person signs in with a recovery code, or another
transportation admin uses Users → "Reset 2-step". If the only admin is
locked out, on the server:

```bash
docker compose -f docker-compose.prod.yml exec -e ISD_API_RESET_MFA_EMAIL=admin@yourdistrict.example.org api python scripts/reset_mfa.py
```

## Email

Password resets, the password-changed notice and new-account set-up
emails go out over SMTP. Any provider works (Amazon SES, Postmark, Brevo,
Google Workspace with an app password, the district's own mail server):
put its settings in `.env` (`ISD_API_SMTP_HOST`, `ISD_API_SMTP_PORT`,
`ISD_API_SMTP_SECURITY`, `ISD_API_SMTP_USERNAME`, `ISD_API_SMTP_PASSWORD`,
`ISD_API_MAIL_FROM`; see `.env.prod.example`). Use 587 with `starttls`
or 465 with `ssl`; `none` is only for a local test inbox. Set up SPF and
DKIM for the sender's domain as the provider describes, or messages land
in spam. Links in emails point at `ISD_API_PUBLIC_WEB_URL` (default: the
first CORS origin).

Without `ISD_API_SMTP_HOST` nothing is emailed: the sign-in page tells
people to ask the transportation office, admins hand out reset links
from Users, and new accounts need a typed password.

To check it, sign out, choose "Forgot your password?" and enter your own
email. `docker compose -f docker-compose.prod.yml logs api` shows
`Couldn't send the '...' email` with the SMTP error if delivery failed.

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
