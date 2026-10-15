# Sourced first by every backup script: run as the postgres user, so files
# under /backups always belong to it, even when started as root with
# `docker compose exec backup ...` (entrypoint.sh has copied the secrets
# where that user can read them).
if [ "$(id -u)" = 0 ]; then
    exec gosu postgres "$0" "$@"
fi
