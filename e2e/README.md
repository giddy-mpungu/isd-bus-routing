# End-to-end tests

The whole system, driven in a real browser (Playwright, Chromium), the way
people use it. Decided by the product owner on 2026-10-15: Playwright with
Chromium; run on every PR; both a fresh install by the runbook and fresh
seeded API + web rounds; everything covered. Single sign-on included
(2026-10-19), against a real Keycloak.

Two harnesses start the system from nothing every time:

| Harness                     | What it does                                                                                                                                                                                                                                                                                                                                                          | Projects                                        |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `scripts/fresh-install.sh`  | Follows `docs/deployment.md` step by step on a Linux host with Docker (code onto the host, secret files, `.env`, build and start, migrations, the first administrator, verify, the first backup and restore check). Round 1 tests the install itself; round 2 removes everything, volumes included, brings it up again, loads the demo district and tests every role. | `install`, then `setup` + `seeded` + `journeys` |
| `scripts/seeded-rounds.mjs` | The real API (SQLite, migrated) and the production web build, the demo district loaded through the API, tested as every role; repeated (`--rounds`, 2 in CI) with nothing shared but the web build. Works on Windows, macOS and Linux. With `--projects setup,integrations` and the outside systems (below), the integrations instead.                                | `setup` + `seeded` + `journeys`                 |

The only differences from a real server: the install uses `localhost`
(Caddy's own certificate instead of Let's Encrypt), mail goes to a captured
inbox (Mailpit) instead of the district's mail server, and backups stay on
the server.

## Running them

Once, to install (the browser download is about 300 MB, outside the repo):

```bash
cd e2e
npm ci
npx playwright install chromium
```

Seeded rounds (needs the api's Python dependencies and `npm ci` in
`services/web`):

```bash
node e2e/scripts/seeded-rounds.mjs --rounds 1
```

Add `--mailpit http://127.0.0.1:8025` with a Mailpit running to include the
email tests, `--skip-build` to reuse the last web build, and Playwright
arguments after `--` (for example `-- --headed` or `-- --grep driver`).

The integrations with outside systems (Docker for Mailpit and Keycloak;
the SIS is a fake started by the harness, `fakes/oneroster.mjs`):

```bash
python dev/keycloak/make_realm.py http://localhost:8090
docker run -d --name isd-e2e-mailpit -p 127.0.0.1:1025:1025 -p 127.0.0.1:8025:8025 axllent/mailpit:latest
docker run -d --name isd-keycloak -p 127.0.0.1:8180:8080 -v "$PWD/dev/keycloak/out:/opt/keycloak/data/import:ro" quay.io/keycloak/keycloak:26.3 start-dev --import-realm
E2E_SSO_USERS=dev/keycloak/out/users.txt node e2e/scripts/seeded-rounds.mjs --rounds 1 --projects setup,integrations --mailpit http://127.0.0.1:8025 --oneroster --maps --worker --api-env dev/keycloak/out/api-sso.env
```

`--api-env` adds the api's single sign-on settings from the realm script,
`--oneroster` starts the fake roster server and points the api at it,
`--maps` does the same for the Census geocoder and OpenRouteService
(`fakes/maps.mjs`, straight roads named after their stops), and
`--worker` runs the background worker every 5 seconds. Without them, those
tests skip.

In CI the seeded rounds run on every PR (`ci.yml`). The fresh install and
the integrations (`e2e-heavy.yml`) run on a PR that touches what they test
(compose files, images, the runbook, sign-in, the SIS, the worker, mail,
migrations, `e2e/`), every Sunday, and from the Actions tab ("Run
workflow"), to stay within the free minutes for a private repository.

The fresh install (Linux, or WSL, with Docker; ports 80, 443 and 8025
free). It installs the code **as committed** (`git archive HEAD`), so commit
local changes first:

```bash
bash e2e/scripts/fresh-install.sh          # removes the test install afterwards
bash e2e/scripts/fresh-install.sh --keep   # leaves it running at https://localhost
```

## What's covered

- `tests/install/` — the API is up and its docs aren't public; every
  response has the security headers; nobody gets in without signing in;
  the first administrator sets up two-step sign-in (codes computed like an
  authenticator app) and gets in with a hardened session cookie; a new
  family's set-up email, choosing a password, forgot-password and the
  password-changed notice, through the captured inbox.
- `tests/seeded/auth.setup.ts` — signs in once as every role of the demo
  district (two-step setup for the roles that need it) and saves the
  sessions.
- `tests/seeded/pages.spec.ts` — every page each role can open loads with
  no error messages, console errors or server errors, and passes WCAG 2.1
  A/AA in the real browser, contrast included; the family and driver pages
  in Spanish too.

- `tests/journeys/` (after the page checks; they change data, each with its
  own people and buses):
  1. A bus to the shop: a maintenance window, "Needs a bus", a spare
     swapped in from the alert, the driver's tablet showing it, back in
     service.
  2. A driver's day: a run from Acknowledge to Complete, a defect report
     that dispatch sees and marks fixed, a late-evening absence.
  3. A family: a ride changed and back, the bus looked for, bus-time emails
     off and on, records downloaded, a correction asked for and accepted
     by the office.
  4. A field trip: a van too small for the class refused, a free driver and
     bus assigned.
  5. Bell times imported (one row refused), a route following them, the
     moved day re-run, the school admin seeing their bells.
  6. Access: each role refused the staff console and the API endpoints it
     isn't for; signed out, nothing opens; a student sees only their own
     record.
  7. An announcement reaching exactly its families and school; every report
     downloading as CSV.
  8. A sick day: needs cover, substitutes ranked, the spare driver assigned.
  9. Account security: a new dispatcher sets up two-step sign-in, makes new
     recovery codes, changes their password (the old one stops working, a
     notice is emailed), signs in with a recovery code (which then doesn't
     work twice); the phone lost, an admin resets two-step sign-in, which
     signs them out, and they set it up again.
  10. A route's stops: three put on Willow Creek's afternoon route, ordered
      and timed by the planner and applied; the driver sees them in order
      with the children at each (directions explain they need
      OpenRouteService), and the family sees when the bus is due.
  11. Stop proposals: new students' homes on file (one placed by hand on
      the map), stops proposed for the school, a new one moved on the map
      and approved, an existing one approved, one turned down; the
      children get their stops.
- `tests/integrations/` (outside systems):
  - Single sign-on with the district's identity provider (Keycloak): a
    driver gets straight in; a dispatcher still passes this system's
    two-step check (the provider didn't report one); someone the district
    knows but this system doesn't is turned away.
  - The SIS roster sync (OneRoster 1.1 behind an OAuth sign-in): a school
    given its SIS id, "Sync now" brings in its two new students with their
    SIS ids, and a second sync changes nothing.
  - Bus-time emails: the worker emails a family when their child's bus
    time moves 10 minutes or more from the plan, and the email's link
    turns them off.
  - Directions (OpenRouteService): the driver follows a route stop by
    stop, with the bus's size and the district's flood-prone crossing sent;
    dispatch closes a road at a stop, the driver is told, and the next
    directions avoid it.
  - Home addresses (US Census geocoder): an unknown address asks for a pin
    on the map; a known one is matched; only the address is ever sent.

Outputs go to `e2e/.out/` (gitignored): the run's generated logins, saved
sessions and server logs. They're for a throwaway fictional district, but
still never committed or uploaded; CI keeps only the report, traces and
logs of a failed run.
