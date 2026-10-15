#!/usr/bin/env bash
# Replaces the database with a backup. DESTRUCTIVE: everything since that
# backup is lost. Stop the api and worker first (docs/deployment.md).
#
# Usage: CONFIRM_RESTORE=<database name> restore.sh [snapshot id | latest]
set -euo pipefail
. /usr/local/lib/as-postgres.sh

snapshot="${1:-latest}"
: "${PGHOST:?}" "${PGUSER:?}" "${PGDATABASE:?}" "${PGPASSWORD_FILE:?}" "${RESTIC_REPOSITORY:?}" "${RESTIC_PASSWORD_FILE:?}"
if [ "${CONFIRM_RESTORE:-}" != "$PGDATABASE" ]; then
    echo "This replaces the whole '$PGDATABASE' database with snapshot '$snapshot'." >&2
    echo "Re-run with CONFIRM_RESTORE=$PGDATABASE to go ahead." >&2
    exit 2
fi
PGPASSWORD="$(cat "$PGPASSWORD_FILE")"
export PGPASSWORD

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
restic restore "$snapshot" --host isd-backup --tag isd --target "$work"
dump="$(find "$work" -name '*.dump' | head -n 1)"
[ -n "$dump" ] || { echo "no dump in snapshot $snapshot" >&2; exit 1; }
echo "$(date -u +%FT%TZ) restore: $(basename "$dump") into $PGDATABASE"
pg_restore --clean --if-exists --no-owner --exit-on-error --dbname="$PGDATABASE" "$dump"
echo "$(date -u +%FT%TZ) restore: done. Start the api and worker again."
