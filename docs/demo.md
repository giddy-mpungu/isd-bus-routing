# Local demo and beta testing

Run the whole system (every dashboard, the API, the solver, and a real
PostgreSQL database) on your own computer for free, loaded with a
fictional school district. You can also optionally share it with beta
testers over a temporary HTTPS link.

This is **the production stack itself** (`docker-compose.prod.yml`)
with a small overlay (`docker-compose.demo.yml`). It is not a separate
"demo mode" of the app. Testers see exactly what a real server would
run: PostgreSQL, Alembic migrations, `ISD_API_ENVIRONMENT=production`,
`Secure` session cookies, and Caddy in front. That's also what makes the
later move to a VPS small (see [Moving to a VPS later](#moving-to-a-vps-later)).

## What you need

- **Docker Desktop** (free for personal use), running. The script
  starts it for you if it's installed but not running.
- Nothing else: no Python, Node, or Postgres installs. Everything builds
  inside containers.

## Start it

From the repo root in PowerShell:

```powershell
scripts\demo.cmd up
```

(`demo.cmd` just runs `scripts\demo.ps1` without you having to change
PowerShell's execution policy. `powershell -ExecutionPolicy Bypass -File scripts\demo.ps1 up`
does the same thing.)

The first run takes a few minutes, because it downloads base images and
builds the api and web images. After that, `up` takes seconds. When it
finishes, it prints:

- the address, **http://localhost:8080**, which only this computer can reach;
- the test inbox, **http://localhost:8025**: every email the demo sends
  (password resets, set-up emails for accounts you add) lands there
  instead of reaching anyone. Also this computer only. While sharing,
  the links in them say `http://localhost:8080`; swap in the tunnel
  address before passing one to a tester;
- one login per role, each with its own randomly generated password.
  They're saved to `secrets\demo-credentials.json` (gitignored), and
  `scripts\demo.cmd credentials` prints them again at any time.

| Log in as | To see |
|---|---|
| `admin@demo.example.org` | Everything: Setup, Users, Templates, Schedule, Field Trips |
| `dispatcher@demo.example.org` | The dispatcher console: Schedule, Field Trips, Templates, Setup |
| `driver.jordan@…`, `driver.sam@…` | The driver app: today's runs, riders by stop, status buttons, reports |
| `school.willowcreek@…` | One school's buses and notices |
| `parent.alvarez@…` | A guardian of two students: ridership toggles, bus location |
| `student.noah@…` | A student's own view |

## The demo district

"Maple Valley ISD" is entirely made up (`services/api/src/isd_api/demo_seed.py`):

- 3 schools, 6 stops, 12 students, 4 drivers, and 4 vehicles (one with
  a wheelchair lift).
- Recurring route and crew templates.
- **14 days of schedule already generated and solved**, starting today.
  The templates run all 7 days so a weekend demo isn't empty.
- District geographic knowledge, two announcements, and an unassigned
  field trip.

The elementary school's runs need the lift bus, so you can watch the
solver respect a vehicle qualification. The bell times overlap, so all
three standing crews are used and every demo driver's app has runs.

It's loaded through the real API, as the admin, so the audit log, the
validation, and the solver all behave exactly as they would for a person
using the UI. It only ever loads into an **empty** database; it refuses
to run if any user already exists.

> **Never put real student or family data into a demo install.** It
> doesn't have a real deployment's safeguards (backups, monitoring,
> a hardened host), and it's often shared over a public link.

## Share it with testers

```powershell
scripts\demo.cmd share
```

This starts the demo (if it isn't already running) plus a free
[Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/),
then prints a public address like `https://some-random-words.trycloudflare.com`.
Send that to your testers.

- **No account, no cost, no router setup.** The tunnel connects outward
  from your laptop, so there's no port-forwarding and your home IP isn't
  revealed. It also provides HTTPS, which the app's `Secure` login
  cookie needs.
- **The address changes every time sharing restarts**, and quick
  tunnels come with no uptime guarantee. That's fine for test sessions,
  but it isn't a permanent home (see the VPS section below).
- **Anyone with the link can reach the login page while it's on.**
  Logins are still required, the passwords are random, and login
  attempts are rate-limited. Even so, run `scripts\demo.cmd unshare`
  when a session is over. That turns the link off and keeps the demo
  running locally.
- **Give each tester their own account** (Users page, as admin) rather
  than passing around the admin login. Then you can see who did what in
  the audit log, and switch someone off without affecting anyone else.
- Your laptop has to stay on and awake while people are testing.

Why not just open it on your Wi-Fi? The demo deliberately listens on
`127.0.0.1` only, so nothing on your network can reach it directly.
Plain `http://<your-laptop-ip>:8080` also wouldn't work: browsers only
store a `Secure` cookie over HTTPS (or on `localhost`), so login would
fail. The tunnel is how other devices get in, including your own phone.

## Everyday commands

| Command | What it does |
|---|---|
| `scripts\demo.cmd up` | Start (or update, after pulling new code: it rebuilds changed images and runs any new migrations). Your data is kept. |
| `scripts\demo.cmd share` / `unshare` | Turn the public test link on / off |
| `scripts\demo.cmd stop` | Stop everything. Data is kept. |
| `scripts\demo.cmd status` | What's running |
| `scripts\demo.cmd logs` | Follow the logs (Ctrl+C to stop following) |
| `scripts\demo.cmd credentials` | Print the demo logins again |
| `scripts\demo.cmd reset` | **Delete all demo data** and the demo's secrets, after you type `RESET` to confirm. The next `up` starts from a fresh district. |

If you also use the dev `docker-compose.yml`, stop it first. Both use
port 8080.

## What's generated, and where

All of it is gitignored, and all of it is generated on the first `up`:

| File | Contents |
|---|---|
| `.env.demo` | Random JWT signing key, the database connection string, and the demo's settings |
| `secrets\demo_postgres_password.txt` | Random database password, handed to Postgres as a Docker secret |
| `secrets\demo-credentials.json` | The demo logins (plain text, since it's a demo: don't reuse these passwords anywhere) |

## Moving to a VPS later

Yes, you can keep everything on your laptop for now and move it later.
The demo already *is* the production setup, so moving means changing
where it runs, not what runs. When you have feedback and want something
always-on:

1. **Rent a small Linux VPS.** 2 GB of RAM is enough to start. Install
   Docker, point a domain's DNS at it, and clone the repo.
2. **Follow [docs/deployment.md](deployment.md)** with `docker-compose.prod.yml`
   on its own, with no demo overlay. Caddy then gets a real Let's Encrypt
   certificate for your domain automatically, so you no longer need the
   tunnel, and the address stops changing.
3. **Decide whether to bring the demo data along:**
   - **Start clean** (recommended for real use): bootstrap a real admin
     and enter real data. The demo district was only for showing people.
   - **Keep the beta environment as is**, including testers' accounts and
     what they created: dump the demo database on your laptop and restore
     it on the VPS.

     ```powershell
     docker compose --env-file .env.demo -f docker-compose.prod.yml -f docker-compose.demo.yml exec -T postgres pg_dump -U isd -f /tmp/demo-backup.sql isd_api
     docker compose --env-file .env.demo -f docker-compose.prod.yml -f docker-compose.demo.yml cp postgres:/tmp/demo-backup.sql demo-backup.sql
     ```

     (The dump is written inside the container and then copied out,
     rather than `pg_dump ... > file`: Windows PowerShell 5.1's `>`
     writes UTF-16, which `psql` can't restore.)

     Copy `demo-backup.sql` to the server and restore it with the `psql`
     command in deployment.md's Backups section. Generate **new** secrets
     on the server rather than copying `.env.demo`, because the demo's
     secrets have lived in plain files on a laptop.

Wanting to rehearse a VPS locally first? A local Linux VM (for example
an Ubuntu VM in Hyper-V or VirtualBox) behaves like a VPS, but it adds
little here. Docker Desktop already runs these containers on Linux
(inside WSL 2), which is the same thing a VPS would run.
