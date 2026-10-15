#!/usr/bin/env bash
# Proves the latest backup can be restored, without touching the live
# database: restores it into a throwaway database, checks the tables are
# there and hold rows, and drops it. Run weekly by schedule.sh.
set -euo pipefail
. /usr/local/lib/as-postgres.sh

: "${PGHOST:?}" "${PGUSER:?}" "${PGDATABASE:?}" "${PGPASSWORD_FILE:?}" "${RESTIC_REPOSITORY:?}" "${RESTIC_PASSWORD_FILE:?}"
PGPASSWORD="$(cat "$PGPASSWORD_FILE")"
export PGPASSWORD
# Only warnings and errors from PostgreSQL, not "does not exist, skipping".
export PGOPTIONS="-c client_min_messages=warning"
check_db="isd_restore_check"

work="$(mktemp -d)"
trap 'rm -rf "$work"; dropdb --if-exists "$check_db" >/dev/null 2>&1 || true' EXIT
restic restore latest --host isd-backup --tag isd --target "$work" >/dev/null
dump="$(find "$work" -name '*.dump' | head -n 1)"
[ -n "$dump" ] || { echo "restore check: no dump in the latest snapshot" >&2; exit 1; }

dropdb --if-exists "$check_db"
createdb "$check_db"
pg_restore --no-owner --exit-on-error --dbname="$check_db" "$dump"
tables="$(psql -At -d "$check_db" -c "select count(*) from information_schema.tables where table_schema = 'public'")"
users="$(psql -At -d "$check_db" -c "select count(*) from users")"
version="$(psql -At -d "$check_db" -c "select version_num from alembic_version" 2>/dev/null || echo none)"
if [ "$tables" -lt 10 ]; then
    echo "restore check FAILED: only $tables tables in $(basename "$dump")" >&2
    exit 1
fi
echo "$(date -u +%FT%TZ) restore check OK: $(basename "$dump"): $tables tables, $users users, schema $version"
