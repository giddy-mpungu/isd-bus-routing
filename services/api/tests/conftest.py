from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from isd_api.db import Base, get_db, make_engine
from isd_api.main import app
from isd_api.models import Role, User
from isd_api.security import hash_password


@pytest.fixture()
def db_session():
    """A fresh in-memory SQLite DB per test, shared across the whole
    test's connections via StaticPool (needed because FastAPI's
    TestClient and the fixture itself both need to see the same DB) —
    make_engine("sqlite://") applies StaticPool automatically."""
    engine = make_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


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
