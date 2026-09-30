from datetime import UTC, datetime, timedelta

import pytest

from isd_api import passwords
from isd_api.models import AuditLogEntry, PasswordResetToken, Role
from tests.conftest import auth_headers, login, make_user

NEW = "yellow-bus-route-7"


@pytest.mark.parametrize(
    ("password", "problem"),
    [
        ("short1", "Use at least 8 characters"),
        ("Password123", "That password is too common; choose another"),
        ("12345678", "That password is too common; choose another"),
        ("pat.driver@example.org", "Don't use your email as your password"),
        ("PAT.DRIVER", "Don't use your email as your password"),
        ("é" * 37, "That password is too long"),
        ("yellow-bus-route-7", None),
    ],
)
def test_password_policy(password, problem):
    assert passwords.policy_problem(password, "pat.driver@example.org") == problem


def test_minimum_length_is_a_setting(monkeypatch):
    monkeypatch.setattr(passwords.settings, "password_min_length", 12)
    assert passwords.policy_problem("eleven-char", "a@example.org") == "Use at least 12 characters"


def test_creating_a_user_checks_the_policy(client, admin_headers):
    response = client.post(
        "/users",
        headers=admin_headers,
        json={
            "email": "new@example.org",
            "password": "password1",
            "full_name": "New",
            "role": "dispatcher",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "That password is too common; choose another"


def _person(client, db_session, email="pat@example.org", role=Role.DISPATCHER):
    user = make_user(db_session, email=email, role=role)
    return user, login(client, email=email)


def test_changing_your_password_signs_out_other_sessions(client, db_session):
    user, first = _person(client, db_session)
    second = login(client, email="pat@example.org")

    response = client.post(
        "/auth/change-password",
        headers=auth_headers(first),
        json={"current_password": "password123", "new_password": NEW},
    )
    assert response.status_code == 200, response.text
    fresh = response.json()["access_token"]

    # Every session from before the change ends, including the one used.
    for old in (first, second):
        ended = client.get("/users/me", headers=auth_headers(old))
        assert ended.status_code == 401
        assert ended.json()["detail"] == "Your password was changed. Sign in again."
    assert client.get("/users/me", headers=auth_headers(fresh)).status_code == 200
    # The browser's cookie was replaced too, so the person stays signed in.
    assert client.get("/users/me").status_code == 200

    wrong = client.post(
        "/auth/login", data={"username": "pat@example.org", "password": "password123"}
    )
    assert wrong.status_code == 401
    login(client, email="pat@example.org", password=NEW)

    entry = db_session.query(AuditLogEntry).filter_by(action="password_changed").one()
    assert entry.entity_id == user.id and entry.actor_user_id == user.id
    assert entry.before_state is None and entry.after_state is None


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"current_password": "nope", "new_password": NEW}, "Your current password is incorrect"),
        (
            {"current_password": "password123", "new_password": "password123"},
            "Choose a password different from your current one",
        ),
        ({"current_password": "password123", "new_password": "short"}, "Use at least 8 characters"),
    ],
)
def test_change_password_refusals(client, db_session, body, detail):
    _, token = _person(client, db_session)
    response = client.post("/auth/change-password", headers=auth_headers(token), json=body)
    assert response.status_code == 400
    assert response.json()["detail"] == detail
    # Nothing changed: the session still works.
    assert client.get("/users/me", headers=auth_headers(token)).status_code == 200


def test_change_password_needs_sign_in_and_is_rate_limited(client, db_session):
    body = {"current_password": "guess", "new_password": NEW}
    assert client.post("/auth/change-password", json=body).status_code == 401

    _, token = _person(client, db_session)
    codes = [
        client.post("/auth/change-password", headers=auth_headers(token), json=body).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [400] * 10
    assert codes[10] == 429


def _issue(client, admin_headers, user_id):
    response = client.post(f"/users/{user_id}/reset-link", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reset_path"].startswith("/reset-password#token=")
    return body, body["reset_path"].split("#token=", 1)[1]


def test_admin_reset_link_sets_a_new_password_once(client, db_session, admin_headers):
    user, old_session = _person(client, db_session, role=Role.DRIVER)
    body, token = _issue(client, admin_headers, user.id)

    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(hours=23, minutes=59) < expires - datetime.now(UTC) <= timedelta(hours=24)
    # Only a hash is stored, and the audit trail never sees the token.
    row = db_session.query(PasswordResetToken).one()
    assert token not in row.token_hash and len(row.token_hash) == 64
    issued = db_session.query(AuditLogEntry).filter_by(action="reset_link_issued").one()
    assert token not in str(issued.after_state)

    done = client.post("/auth/reset-password", json={"token": token, "new_password": NEW})
    assert done.status_code == 204, done.text
    assert client.get("/users/me", headers=auth_headers(old_session)).status_code == 401
    login(client, email="pat@example.org", password=NEW)
    assert db_session.query(AuditLogEntry).filter_by(action="password_reset").count() == 1

    again = client.post(
        "/auth/reset-password", json={"token": token, "new_password": "another-pass-9"}
    )
    assert again.status_code == 400
    assert "expired or was already used" in again.json()["detail"]


def test_a_new_link_cancels_the_old_one(client, db_session, admin_headers):
    user, _ = _person(client, db_session)
    _, first = _issue(client, admin_headers, user.id)
    _, second = _issue(client, admin_headers, user.id)
    assert (
        client.post("/auth/reset-password", json={"token": first, "new_password": NEW}).status_code
        == 400
    )
    assert (
        client.post("/auth/reset-password", json={"token": second, "new_password": NEW}).status_code
        == 204
    )


def test_a_weak_password_leaves_the_link_usable(client, db_session, admin_headers):
    user, _ = _person(client, db_session)
    _, token = _issue(client, admin_headers, user.id)
    weak = client.post("/auth/reset-password", json={"token": token, "new_password": "iloveyou"})
    assert weak.status_code == 400
    assert weak.json()["detail"] == "That password is too common; choose another"
    assert (
        client.post("/auth/reset-password", json={"token": token, "new_password": NEW}).status_code
        == 204
    )


def test_expired_links_and_inactive_accounts_are_refused(client, db_session, admin_headers):
    user, _ = _person(client, db_session)
    _, token = _issue(client, admin_headers, user.id)
    row = db_session.query(PasswordResetToken).one()
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    assert (
        client.post("/auth/reset-password", json={"token": token, "new_password": NEW}).status_code
        == 400
    )

    _, token = _issue(client, admin_headers, user.id)
    client.patch(f"/users/{user.id}", headers=admin_headers, json={"is_active": False})
    assert (
        client.post("/auth/reset-password", json={"token": token, "new_password": NEW}).status_code
        == 400
    )
    refused = client.post(f"/users/{user.id}/reset-link", headers=admin_headers)
    assert refused.status_code == 409


def test_only_transportation_admins_issue_links(client, db_session, admin_headers):
    user, token = _person(client, db_session)
    assert (
        client.post(f"/users/{user.id}/reset-link", headers=auth_headers(token)).status_code == 403
    )
    assert client.post("/users/99999/reset-link", headers=admin_headers).status_code == 404
