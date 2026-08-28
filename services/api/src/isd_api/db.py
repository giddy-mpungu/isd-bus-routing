"""SQLAlchemy engine and session management.

Uses plain, dialect-portable column types (see models.py) so the same
schema runs against SQLite (used by the test suite and this sandboxed
development environment, which has no PostgreSQL server available) and
PostgreSQL (the intended production database per ADR 0003). PostGIS-
specific geospatial types are deliberately NOT used yet — see ADR 0006.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from isd_api.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        # Needed for SQLite + FastAPI's threaded test client / request handling.
        connect_args = {"check_same_thread": False}
    return create_engine(settings.database_url, connect_args=connect_args)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
