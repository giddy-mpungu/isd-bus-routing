# Backups (Phase 5): nightly encrypted database backups with restic.
# Same PostgreSQL major version as the database (docker-compose.prod.yml),
# so pg_dump/pg_restore match the server. restic comes from Debian's
# signed package repository. See docs/deployment.md, "Backups".
FROM postgres:16

RUN apt-get update \
    && apt-get install -y --no-install-recommends restic ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backup.sh restore.sh check-restore.sh schedule.sh entrypoint.sh /usr/local/bin/
COPY as-postgres.sh /usr/local/lib/
RUN chmod 0755 /usr/local/bin/backup.sh /usr/local/bin/restore.sh \
        /usr/local/bin/check-restore.sh /usr/local/bin/schedule.sh \
        /usr/local/bin/entrypoint.sh \
    && mkdir -p /backups && chown postgres:postgres /backups

# Starts as root only to copy the secrets where the postgres user can read
# them (entrypoint.sh), then works as that user (gosu, from the postgres
# image).
WORKDIR /backups
ENTRYPOINT ["entrypoint.sh"]
CMD ["schedule.sh"]
