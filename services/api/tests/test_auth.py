from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user


def test_login_succeeds_with_correct_credentials(client, db_session):
    make_user(
        db_session, email="a@example.org", role=Role.TRANSPORTATION_ADMIN, password="correct-horse"
    )
    response = client.post(
        "/auth/login", data={"username": "a@example.org", "password": "correct-horse"}
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_fails_with_wrong_password(client, db_session):
    make_user(
        db_session, email="a@example.org", role=Role.TRANSPORTATION_ADMIN, password="correct-horse"
    )
    response = client.post("/auth/login", data={"username": "a@example.org", "password": "wrong"})
    assert response.status_code == 401


def test_login_fails_for_unknown_user(client):
    response = client.post(
        "/auth/login", data={"username": "nobody@example.org", "password": "whatever1"}
    )
    assert response.status_code == 401


def test_login_fails_for_inactive_user(client, db_session):
    make_user(
        db_session,
        email="a@example.org",
        role=Role.TRANSPORTATION_ADMIN,
        password="correct-horse",
        is_active=False,
    )
    response = client.post(
        "/auth/login", data={"username": "a@example.org", "password": "correct-horse"}
    )
    assert response.status_code == 401


def test_protected_endpoint_requires_token(client):
    response = client.get("/users/me")
    assert response.status_code == 401


def test_protected_endpoint_rejects_garbage_token(client):
    response = client.get("/users/me", headers=auth_headers("not-a-real-token"))
    assert response.status_code == 401


def test_me_returns_the_logged_in_user(client, db_session):
    make_user(db_session, email="a@example.org", role=Role.DISPATCHER, password="correct-horse")
    token = login(client, email="a@example.org", password="correct-horse")
    response = client.get("/users/me", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.json()["email"] == "a@example.org"
    assert response.json()["role"] == "dispatcher"
