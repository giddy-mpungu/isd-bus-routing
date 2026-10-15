#!/bin/sh
# Docker Compose mounts secret files with the server file's own owner and
# mode (chmod 600 in docs/deployment.md), so the postgres user this image
# works as can't read them. As root, copy the two secrets where only that
# user can, then run as it. Scripts started with `docker compose exec`
# (which skips this) switch user themselves (as-postgres.sh).
set -eu
install -d -o postgres -g postgres -m 0700 /run/backup-secrets
for name in postgres_password restic_password; do
    install -o postgres -g postgres -m 0400 "/run/secrets/$name" "/run/backup-secrets/$name"
done
exec gosu postgres "$@"
