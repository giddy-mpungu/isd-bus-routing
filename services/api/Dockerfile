# Build context is the REPO ROOT, not services/api — this image needs
# both services/solver and services/api. Build from the repo root:
#   docker build -f services/api/Dockerfile -t isd-api .

FROM python:3.12-slim

WORKDIR /app

# services/api imports isd_solver directly (ADR 0003: in-process
# library call, not a network call) but does not declare it as a
# pyproject dependency — no portable relative-path dependency spec
# exists for a sibling package in this monorepo with no package index
# to publish to (see the comment in services/api/pyproject.toml and
# docs/REBOOT.md). Install order matters: solver first, always.
COPY services/solver ./services/solver
RUN pip install --no-cache-dir -e ./services/solver

COPY services/api ./services/api
# The `postgres` extra (psycopg) is installed unconditionally so this
# one image works for both the dev compose file (SQLite) and
# docker-compose.prod.yml (PostgreSQL, ADR 0003/0006) — no separate
# production image to keep in sync.
RUN pip install --no-cache-dir -e "./services/api[postgres]"

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
# A named volume's mount point is created owned by root by default —
# without this, the non-root user below can't write the SQLite file
# docker-compose.yml's default ISD_API_DATABASE_URL points at.
RUN mkdir -p /data && chown -R appuser:appuser /data
USER appuser

WORKDIR /app/services/api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

# No ISD_API_ENVIRONMENT default here on purpose. The app itself
# refuses to start in production with the insecure default JWT secret
# (Settings.require_production_ready(), src/isd_api/config.py) — a
# Dockerfile default here would just be one more place a real secret
# could be silently forgotten. Operators set ISD_API_ENVIRONMENT,
# ISD_API_JWT_SECRET_KEY, ISD_API_DATABASE_URL, and
# ISD_API_CORS_ALLOWED_ORIGINS at deploy time (see docker-compose.yml
# for the local/dev defaults).
#
# Migrations are NOT run automatically on container start (multiple
# replicas would race to migrate concurrently) — run them as a
# one-off: `docker compose run --rm api alembic upgrade head`.
CMD ["uvicorn", "isd_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
