#!/usr/bin/env node
/**
 * Fresh API + web, seeded, tested — several times over.
 *
 * Each round starts from nothing: an empty SQLite database, migrations, the
 * real API server, the fictional demo district loaded through the API
 * (scripts/seed_demo.py, which a second time must refuse), the built web
 * app served as in production, then the browser tests as every role
 * (Playwright projects `setup` and `seeded`). Rounds share nothing but the
 * web build, so something that only works once shows up.
 *
 *   node e2e/scripts/seeded-rounds.mjs [--rounds 2] [--mailpit http://127.0.0.1:8025]
 *       [--python python3] [--skip-build] [-- extra playwright arguments]
 *
 * --mailpit: a running Mailpit (SMTP on port 1025 of the same host) for the
 * email tests; without it they're skipped. Needs Python with the api's
 * dependencies (services/api), `npm ci` in services/web and e2e, and
 * Playwright's Chromium (npx playwright install chromium). Ports 8090 and
 * 4173 must be free. Works on Linux, macOS and Windows. (Written in Node
 * rather than Python: a Microsoft Store Python gives the programs it starts
 * a private AppData, where Playwright's browser can't be found.)
 */
import { spawn, spawnSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { createWriteStream, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const API_DIR = join(REPO, 'services', 'api')
const WEB_DIR = join(REPO, 'services', 'web')
const E2E_DIR = join(REPO, 'e2e')
const API_PORT = 8090
const WEB_PORT = 4173
const API_URL = `http://localhost:${API_PORT}`
const WEB_URL = `http://localhost:${WEB_PORT}`
const WINDOWS = process.platform === 'win32'
const NPX = WINDOWS ? 'npx.cmd' : 'npx'
const NPM = WINDOWS ? 'npm.cmd' : 'npm'

function parseArgs(argv) {
  const options = {
    rounds: 2,
    mailpit: process.env.E2E_MAILPIT_URL || '',
    python: '',
    skipBuild: false,
  }
  const extra = []
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--') (extra.push(...argv.slice(i + 1)), (i = argv.length))
    else if (arg === '--rounds') options.rounds = Number(argv[++i])
    else if (arg === '--mailpit') options.mailpit = argv[++i]
    else if (arg === '--python') options.python = argv[++i]
    else if (arg === '--skip-build') options.skipBuild = true
    else extra.push(arg)
  }
  options.python ||= WINDOWS ? 'python' : 'python3'
  return { options, extra }
}

const step = (text) => console.log(`\n==> ${text}`)

function run(command, args, { cwd, env, capture = false } = {}) {
  const result = spawnSync(command, args, {
    cwd,
    env: env ?? process.env,
    stdio: capture ? ['ignore', 'pipe', 'inherit'] : 'inherit',
    shell: WINDOWS && command.endsWith('.cmd'),
  })
  return { code: result.status ?? 1, stdout: result.stdout?.toString() ?? '' }
}

function must(result, what) {
  if (result.code !== 0) throw new Error(`${what} failed (exit ${result.code})`)
  return result
}

/** A server in the background, logging to a file; stop() ends it and its children. */
function start(command, args, { cwd, env, log }) {
  const out = createWriteStream(log)
  const child = spawn(command, args, {
    cwd,
    env,
    detached: !WINDOWS,
    shell: WINDOWS && command.endsWith('.cmd'),
  })
  child.stdout.pipe(out)
  child.stderr.pipe(out)
  return {
    stop() {
      if (child.exitCode !== null) return
      if (WINDOWS) spawnSync('taskkill', ['/T', '/F', '/PID', String(child.pid)])
      else process.kill(-child.pid, 'SIGTERM')
    },
  }
}

async function waitFor(url, what, seconds = 60) {
  const deadline = Date.now() + seconds * 1000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Not up yet.
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`${what} never answered ${url}`)
}

function apiEnv(database, mailpit) {
  const env = {
    ...process.env,
    ISD_API_DATABASE_URL: `sqlite:///${database.replaceAll('\\', '/')}`,
    ISD_API_JWT_SECRET_KEY: randomBytes(32).toString('hex'),
    ISD_API_MFA_ENCRYPTION_KEY: randomBytes(32).toString('base64url') + '=',
    ISD_API_CORS_ALLOWED_ORIGINS: JSON.stringify([WEB_URL]),
    ISD_API_PUBLIC_WEB_URL: WEB_URL,
    PYTHONPATH: join(API_DIR, 'src'),
  }
  if (mailpit) {
    Object.assign(env, {
      ISD_API_SMTP_HOST: new URL(mailpit).hostname,
      ISD_API_SMTP_PORT: '1025',
      ISD_API_SMTP_SECURITY: 'none',
      ISD_API_MAIL_FROM: 'Transportation Office <transportation@e2e.invalid>',
    })
  }
  return env
}

async function runRound(number, { mailpit, python }, extra) {
  const out = join(E2E_DIR, '.out', 'seeded', `round${number}`)
  rmSync(out, { recursive: true, force: true })
  mkdirSync(out, { recursive: true })
  const work = mkdtempSync(join(tmpdir(), 'isd-e2e-'))
  const env = apiEnv(join(work, 'e2e.db'), mailpit)
  const servers = []
  try {
    step(`Round ${number}: an empty database, migrated`)
    must(run(python, ['-m', 'alembic', 'upgrade', 'head'], { cwd: API_DIR, env }), 'Migrations')

    step(`Round ${number}: the API`)
    servers.push(
      start(python, ['-m', 'uvicorn', 'isd_api.main:app', '--port', String(API_PORT)], {
        cwd: API_DIR,
        env,
        log: join(out, 'api.log'),
      }),
    )
    await waitFor(`${API_URL}/health`, 'The API')

    step(`Round ${number}: loading the demo district`)
    const seedEnv = { ...env, ISD_DEMO_SEED_API: API_URL }
    const seeded = must(
      run(python, ['scripts/seed_demo.py'], { cwd: API_DIR, env: seedEnv, capture: true }),
      'The seed',
    )
    writeFileSync(join(out, 'credentials.json'), seeded.stdout)
    console.log(`Seeded ${JSON.parse(seeded.stdout).length} logins`)
    const again = run(python, ['scripts/seed_demo.py'], {
      cwd: API_DIR,
      env: seedEnv,
      capture: true,
    })
    if (again.code !== 3)
      throw new Error(`A second seed should exit 3 (seeded already), not ${again.code}`)

    step(`Round ${number}: the web app`)
    servers.push(
      start(NPX, ['--no-install', 'vite', 'preview', '--port', String(WEB_PORT), '--strictPort'], {
        cwd: WEB_DIR,
        env: process.env,
        log: join(out, 'web.log'),
      }),
    )
    await waitFor(WEB_URL, 'The web app')

    step(`Round ${number}: browser tests as every role`)
    return run(
      NPX,
      ['--no-install', 'playwright', 'test', '--project=setup', '--project=seeded', ...extra],
      {
        cwd: E2E_DIR,
        env: {
          ...process.env,
          E2E_BASE_URL: WEB_URL,
          E2E_API_URL: API_URL,
          E2E_MAILPIT_URL: mailpit,
          E2E_OUT: out,
        },
      },
    ).code
  } finally {
    for (const server of servers.reverse()) server.stop()
    // Give Windows a moment to release the database file.
    await new Promise((r) => setTimeout(r, 1000))
    rmSync(work, { recursive: true, force: true, maxRetries: 5 })
  }
}

const { options, extra } = parseArgs(process.argv.slice(2))
if (!options.skipBuild) {
  step('Building the web app (once, shared by every round)')
  must(
    run(NPM, ['run', 'build'], {
      cwd: WEB_DIR,
      env: { ...process.env, VITE_API_BASE_URL: API_URL },
    }),
    'The web build',
  )
}
const failed = []
for (let round = 1; round <= options.rounds; round++) {
  try {
    if ((await runRound(round, options, extra)) !== 0) failed.push(round)
  } catch (error) {
    console.error(error.message)
    failed.push(round)
  }
}
if (failed.length) {
  console.error(`\nFailed rounds: ${failed.join(', ')}`)
  process.exit(1)
}
console.log(`\nAll ${options.rounds} rounds passed.`)
