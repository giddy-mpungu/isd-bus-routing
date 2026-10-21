#!/usr/bin/env bash
# A first-time install of isd-bus-routing on a Linux host with Docker,
# following docs/deployment.md step by step, then the browser tests:
#
#   Round 1, "install": runbook steps 2-8 (code onto the host, secrets,
#   .env, build and start, migrations, the first administrator, verify),
#   the runbook's first backup and restore check, then e2e project
#   `install` (the first administrator signs in, email, security headers).
#
#   Round 2, "seeded": everything removed, volumes included, and brought up
#   from nothing again; the fictional demo district loaded
#   (scripts/seed_demo.py); then e2e projects `setup` and `seeded` as every
#   role.
#
# What differs from a real server, and only this: the domain is
# `localhost` (Caddy serves HTTPS with its own local certificate instead of
# Let's Encrypt), mail goes to a captured inbox (install/docker-compose.e2e.yml),
# and backups go to the server's own volume instead of off-site storage.
#
# Usage: e2e/scripts/fresh-install.sh [--keep]
#   --keep  leave the stack running afterwards (default: remove it).
# Needs: docker with the compose plugin, openssl, python3, git, node/npm
# (for Playwright), and ports 80, 443 and 8025 free. Installs the code as
# committed (git archive HEAD): commit first to test local changes.
set -euo pipefail

KEEP=0
[[ "${1:-}" == "--keep" ]] && KEEP=1

REPO="$(git rev-parse --show-toplevel)"
E2E="$REPO/e2e"
OUT="$E2E/.out/install"
HOST_DIR="${INSTALL_DIR:-$(mktemp -d)}"
PROJECT=isd-e2e-install
rm -rf "$OUT" && mkdir -p "$OUT"

step() { printf '\n==> %s\n' "$*"; }
compose() {
  docker compose -p "$PROJECT" -f docker-compose.prod.yml -f docker-compose.e2e.yml "$@"
}
# Set KEY=value in .env, replacing the line .env.prod.example has for it.
set_env() {
  python3 - "$1" "$2" <<'PY'
import sys
key, value = sys.argv[1], sys.argv[2]
lines = open(".env", encoding="utf-8").read().split("\n")
out, done = [], False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}")
        done = True
    else:
        out.append(line)
if not done:
    out.append(f"{key}={value}")
open(".env", "w", encoding="utf-8").write("\n".join(out))
PY
}
cleanup() {
  if [[ $KEEP -eq 0 && -f "$HOST_DIR/docker-compose.prod.yml" ]]; then
    step "Removing the test install"
    (cd "$HOST_DIR" && compose down -v --remove-orphans >/dev/null 2>&1 || true)
    [[ -z "${INSTALL_DIR:-}" ]] && rm -rf "$HOST_DIR"
  fi
}
trap cleanup EXIT

wait_for_health() {
  for _ in $(seq 1 60); do
    if curl -sfk https://localhost/api/health >/dev/null; then return 0; fi
    sleep 2
  done
  echo "The API never answered https://localhost/api/health" >&2
  (cd "$HOST_DIR" && compose ps && compose logs --tail 80 api caddy) >&2
  return 1
}

# --- Runbook step 2: get the code onto the host --------------------------
step "2. Code onto the host ($HOST_DIR)"
git -C "$REPO" archive --format=tar HEAD | tar -x -C "$HOST_DIR"
cp "$E2E/install/docker-compose.e2e.yml" "$HOST_DIR/"
cd "$HOST_DIR"

# --- Step 3: the secret files ---------------------------------------------
step "3. Secret files"
mkdir -p secrets
openssl rand -hex 32 | tr -d '\n' > secrets/postgres_password.txt
openssl rand -hex 32 | tr -d '\n' > secrets/restic_password.txt
chmod 600 secrets/postgres_password.txt secrets/restic_password.txt

# --- Step 4: .env from the example, every required value filled ----------
step "4. .env"
cp .env.prod.example .env
set_env ISD_API_DATABASE_URL "postgresql+psycopg://isd:$(cat secrets/postgres_password.txt)@postgres:5432/isd_api"
set_env ISD_API_JWT_SECRET_KEY "$(openssl rand -base64 48 | tr -d '\n')"
set_env ISD_API_MFA_ENCRYPTION_KEY "$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
set_env ISD_API_CORS_ALLOWED_ORIGINS '["https://localhost"]'
set_env ISD_API_PUBLIC_WEB_URL "https://localhost"
set_env PUBLIC_API_ORIGIN "https://localhost/api"
set_env CADDY_DOMAIN "localhost"
set_env RESTIC_REPOSITORY "/backups/restic"
set_env ISD_API_SMTP_HOST "mailpit"
set_env ISD_API_SMTP_PORT "1025"
set_env ISD_API_SMTP_SECURITY "none"
set_env ISD_API_MAIL_FROM '"Transportation Office <transportation@e2e.invalid>"'

bring_up() {
  # --- Step 5: build and start. The backup service reports unhealthy
  # until its first backup, so it's started after (as in the runbook's
  # Backups section).
  step "5. Build and start"
  compose up -d --build --wait postgres routing mailpit api worker web caddy
  # --- Step 6: migrations
  step "6. Migrations"
  compose run --rm api alembic upgrade head
}

# ========================= Round 1: the install ===========================
bring_up

step "7. The first administrator"
ADMIN_EMAIL="first.admin@e2e.example.org"
ADMIN_PASSWORD="$(openssl rand -hex 16)"
compose run --rm \
  -e ISD_API_BOOTSTRAP_EMAIL="$ADMIN_EMAIL" \
  -e ISD_API_BOOTSTRAP_PASSWORD="$ADMIN_PASSWORD" \
  -e ISD_API_BOOTSTRAP_NAME="First Admin (e2e)" \
  api python scripts/bootstrap_admin.py

step "8. Verify"
wait_for_health
curl -sfk https://localhost/api/health
echo

step "Backups: the first one by hand, and a restore check"
compose up -d backup
compose exec -T backup backup.sh manual
compose exec -T backup check-restore.sh

step "Browser tests: the install"
cd "$E2E"
E2E_BASE_URL=https://localhost E2E_API_URL=https://localhost/api \
  E2E_MAILPIT_URL=http://127.0.0.1:8025 E2E_OUT="$OUT/round1" \
  E2E_ADMIN_EMAIL="$ADMIN_EMAIL" E2E_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  npx --no-install playwright test --project=install
cd "$HOST_DIR"

# ============ Round 2: from nothing again, with the demo district ==========
step "Removing everything, volumes included, and starting again"
compose down -v --remove-orphans
bring_up
wait_for_health

step "Loading the fictional demo district"
mkdir -p "$OUT/round2"
compose exec -T api python scripts/seed_demo.py > "$OUT/round2/credentials.json"
echo "Seeded $(python3 -c "import json;print(len(json.load(open('$OUT/round2/credentials.json'))))") logins"

step "Seeding twice is refused, not doubled"
set +e
compose exec -T api python scripts/seed_demo.py > /dev/null
code=$?
set -e
[[ $code -eq 3 ]] || { echo "A second seed should exit 3 (already seeded), got $code" >&2; exit 1; }

step "The routing engine times a bus between two demo schools"
compose exec -T api python scripts/check_routing_engine.py

step "Browser tests: every role in the demo district"
cd "$E2E"
E2E_BASE_URL=https://localhost E2E_API_URL=https://localhost/api E2E_ROUTING_ENGINE=1 \
  E2E_MAILPIT_URL=http://127.0.0.1:8025 E2E_OUT="$OUT/round2" \
  npx --no-install playwright test --project=setup --project=seeded --project=journeys

step "The fresh install passed both rounds"
