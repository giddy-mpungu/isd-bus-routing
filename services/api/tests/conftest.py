from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from isd_api.db import Base, get_db, make_engine
from isd_api.main import app
from isd_api.models import Role, User
from isd_api.security import hash_password

# Unset in every normal run (local or CI) — the entire suite runs
# against in-memory SQLite by default, same as always. The
# api-postgres CI job (.github/workflows/ci.yml) sets this to a real
# postgresql+psycopg:// URL so the exact same suite, unmodified, also
# proves out against production's real target database (ADR 0003/0006).
_TEST_DATABASE_URL = os.environ.get("ISD_API_TEST_DATABASE_URL")


@pytest.fixture()
def db_session():
    """A fresh DB per test. Against the SQLite default, this is an
    in-memory database shared across the test's own connections via
    StaticPool (needed because FastAPI's TestClient and the fixture
    itself must see the same DB) — make_engine("sqlite://") applies
    StaticPool automatically. Against a real server (Postgres CI job),
    it's create-all/drop-all per test on a shared instance instead —
    slower, but proves real per-test isolation still holds."""
    engine = make_engine(_TEST_DATABASE_URL or "sqlite://")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def _get_db_override():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_user(
    db_session, *, email: str, role: Role, password: str = "password123", **kwargs
) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=kwargs.pop("full_name", email.split("@")[0]),
        role=role,
        **kwargs,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def login(client: TestClient, *, email: str, password: str = "password123") -> str:
    response = client.post("/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_token(client, db_session) -> str:
    make_user(db_session, email="admin@example.org", role=Role.TRANSPORTATION_ADMIN)
    return login(client, email="admin@example.org")


@pytest.fixture()
def admin_headers(admin_token) -> dict:
    return auth_headers(admin_token)


# Tests use fixed service dates. Pin the ridership rules' clock well before
# them, so "past day" and "after the cutoff" checks don't start failing as
# real time moves on. Tests of those rules set their own time.
PINNED_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pin_ridership_clock(monkeypatch):
    monkeypatch.setattr("isd_api.ridership_rules.utc_now", lambda: PINNED_NOW)


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    """login_rate_limiter is process-global state (services/api/src/
    isd_api/security.py) — TestClient requests all share
    request.client.host == 'testclient', so without a reset between
    tests, attempts would accumulate across unrelated tests and cause
    spurious 429s."""
    from isd_api.security import login_rate_limiter

    login_rate_limiter.reset()
    yield
