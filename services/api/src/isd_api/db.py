"""SQLAlchemy engine and session management.

Uses plain, dialect-portable column types (see models.py) so the same
schema runs against SQLite (used by the test suite and this sandboxed
development environment, which has no PostgreSQL server available) and
PostgreSQL (the intended production database per ADR 0003). PostGIS-
specific geospatial types are deliberately NOT used yet — see ADR 0006.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from isd_api.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None) -> Engine:
    """Build an engine for `database_url` (defaults to `settings.database_url`).

    This is the one place engine construction happens — the app, the
    test suite (`tests/conftest.py`), and `scripts/bootstrap_admin.py`
    all call this instead of each hand-rolling `create_engine(...)`, so
    pool behavior can't silently drift between them.

    `pool_pre_ping` is on unconditionally: without it, a connection
    that a cloud database dropped for being idle looks fine to
    SQLAlchemy until a request tries to use it and gets a stale-
    connection error instead of a clean retry.
    """
    url = database_url if database_url is not None else settings.database_url
    connect_args: dict[str, Any] = {}
    engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}

    if url.startswith("sqlite"):
        # Needed for SQLite + FastAPI's threaded test client / request handling.
        connect_args["check_same_thread"] = False
        if ":memory:" in url or url == "sqlite://":
            # A plain in-memory SQLite DB is per-connection — StaticPool
            # keeps every caller on the same connection so they all see
            # the same database (used by the test suite for per-test
            # isolation via a fresh in-memory DB each time).
            engine_kwargs["poolclass"] = StaticPool
    else:
        # Pool tuning only makes sense for a real server-backed database
        # (production target: PostgreSQL, ADR 0003) — SQLite has no
        # server-side connection limit to budget against.
        engine_kwargs["pool_size"] = settings.db_pool_size
        engine_kwargs["max_overflow"] = settings.db_max_overflow
        engine_kwargs["pool_recycle"] = settings.db_pool_recycle_seconds

    return create_engine(url, connect_args=connect_args, **engine_kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # Without this, an exception raised after a partial write
        # leaves the session's transaction open until close() —
        # rolling back explicitly makes the failure state unambiguous
        # instead of relying on close()'s implicit discard.
        db.rollback()
        raise
    finally:
        db.close()
