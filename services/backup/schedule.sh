#!/usr/bin/env bash
# The backup container's main loop: a backup every night at BACKUP_TIME
# (HH:MM, in TZ), and on Sundays a restore check afterwards. A failure is
# logged loudly and retried the next night; the container keeps running.
set -uo pipefail
. /usr/local/lib/as-postgres.sh

BACKUP_TIME="${BACKUP_TIME:-02:00}"
echo "$(date) backup schedule: every night at $BACKUP_TIME ($TZ); restore check on Sundays"
while true; do
    now="$(date +%s)"
    next="$(date -d "today $BACKUP_TIME" +%s)"
    [ "$next" -gt "$now" ] || next="$(date -d "tomorrow $BACKUP_TIME" +%s)"
    sleep "$((next - now))"
    backup.sh nightly || echo "$(date) BACKUP FAILED: see the messages above" >&2
    if [ "$(date +%u)" = 7 ]; then
        check-restore.sh || echo "$(date) RESTORE CHECK FAILED: see the messages above" >&2
    fi
done
