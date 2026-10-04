#!/usr/bin/env bash
# One backup: a pg_dump of the whole database, kept on this server under
# /backups/local (the newest KEEP_LOCAL) and sent, encrypted, to the
# restic repository (RESTIC_REPOSITORY: S3-compatible storage off the
# server, or a folder for the laptop demo). Old snapshots are thinned to
# 7 daily, 4 weekly and 12 monthly.
#
# Usage: backup.sh [reason]   reason: nightly (default), pre-migration, manual
set -euo pipefail

reason="${1:-nightly}"
case "$reason" in nightly|pre-migration|manual) ;; *) echo "unknown reason: $reason" >&2; exit 2 ;; esac
: "${PGHOST:?}" "${PGUSER:?}" "${PGDATABASE:?}" "${PGPASSWORD_FILE:?}" "${RESTIC_REPOSITORY:?}" "${RESTIC_PASSWORD_FILE:?}"
KEEP_LOCAL="${KEEP_LOCAL:-7}"
PGPASSWORD="$(cat "$PGPASSWORD_FILE")"
export PGPASSWORD

mkdir -p /backups/local
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dump="/backups/local/isd-${stamp}-${reason}.dump"
echo "$(date -u +%FT%TZ) backup ($reason): dumping $PGDATABASE"
pg_dump --format=custom --no-owner --file="$dump.partial" "$PGDATABASE"
mv "$dump.partial" "$dump"

# Only the newest few stay on this server; restic keeps the history.
ls -1t /backups/local/*.dump | tail -n +"$((KEEP_LOCAL + 1))" | xargs -r rm --

if ! restic cat config >/dev/null 2>&1; then
    echo "$(date -u +%FT%TZ) backup: creating the restic repository"
    restic init
fi
restic backup --quiet --host isd-backup --tag isd --tag "$reason" "$dump"
restic forget --quiet --host isd-backup --tag isd \
    --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune

date -u +%FT%TZ > /backups/last-success
echo "$(date -u +%FT%TZ) backup ($reason): done, $(du -h "$dump" | cut -f1)"
