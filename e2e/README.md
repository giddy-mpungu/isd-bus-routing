# End-to-end tests

The whole system, driven in a real browser (Playwright, Chromium), the way
people use it. Decided by the product owner on 2026-10-15: Playwright with
Chromium; run on every PR; both a fresh install by the runbook and fresh
seeded API + web rounds; everything covered.

Two harnesses start the system from nothing every time:

| Harness                     | What it does                                                                                                                                                                                                                                                                                                                                                          | Projects                           |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `scripts/fresh-install.sh`  | Follows `docs/deployment.md` step by step on a Linux host with Docker (code onto the host, secret files, `.env`, build and start, migrations, the first administrator, verify, the first backup and restore check). Round 1 tests the install itself; round 2 removes everything, volumes included, brings it up again, loads the demo district and tests every role. | `install`, then `setup` + `seeded` |
| `scripts/seeded-rounds.mjs` | The real API (SQLite, migrated) and the production web build, the demo district loaded through the API, tested as every role; repeated (`--rounds`, 2 in CI) with nothing shared but the web build. Works on Windows, macOS and Linux.                                                                                                                                | `setup` + `seeded`                 |

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

Outputs go to `e2e/.out/` (gitignored): the run's generated logins, saved
sessions and server logs. They're for a throwaway fictional district, but
still never committed or uploaded; CI keeps only the report, traces and
logs of a failed run.
