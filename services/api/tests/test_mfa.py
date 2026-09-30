import base64
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet

from isd_api import mfa
from isd_api.config import Settings, settings
from isd_api.models import AuditLogEntry, MfaRecoveryCode, Role, User
from isd_api.security import MFA_PENDING_COOKIE_NAME, create_access_token
from tests.conftest import auth_headers, login, make_user

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.fixture()
def clock(monkeypatch):
    """Controls the time codes are checked against."""
    now = {"t": 1_790_000_000.0}
    monkeypatch.setattr(mfa.time, "time", lambda: now["t"])
    return now


@pytest.fixture()
def staff_need_mfa(monkeypatch):
    monkeypatch.setattr(settings, "mfa_required_roles", ["transportation_admin", "dispatcher"])


def _code(secret, clock, offset_steps=0):
    return mfa.code_at(secret, mfa.current_step(clock["t"]) + offset_steps)


def _password_step(client, email="dana@example.org", password="password123"):
    response = client.post("/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _enrol(client, clock, email="dana@example.org"):
    """Signs in for the first time and sets up the authenticator."""
    assert _password_step(client, email)["mfa"] == "setup"
    setup = client.post("/auth/mfa/setup").json()
    confirmed = client.post("/auth/mfa/confirm", json={"code": _code(setup["secret"], clock)})
    assert confirmed.status_code == 200, confirmed.text
    return setup["secret"], confirmed.json()


@pytest.mark.parametrize(("unix_time", "code"), [(59, "287082"), (1111111109, "081804")])
def test_codes_match_rfc_6238(unix_time, code):
    assert mfa.code_at(RFC_SECRET, mfa.current_step(unix_time)) == code


def test_staff_set_up_an_authenticator_at_first_sign_in(client, db_session, clock, staff_need_mfa):
    user = make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    first = _password_step(client)
    assert first == {
        "access_token": None,
        "token_type": "bearer",
        "mfa": "setup",
        "recovery_codes_left": None,
    }
    pending = client.cookies.get(MFA_PENDING_COOKIE_NAME)
    assert pending is not None
    # Half-way through sign-in isn't signed in, not even with the cookie as a bearer token.
    assert client.get("/users/me").status_code == 401
    assert client.get("/users/me", headers=auth_headers(pending)).status_code == 401

    setup = client.post("/auth/mfa/setup").json()
    uri = urlparse(setup["otpauth_uri"])
    assert uri.scheme == "otpauth" and uri.netloc == "totp"
    assert parse_qs(uri.query)["secret"] == [setup["secret"]]
    assert parse_qs(uri.query)["issuer"] == ["isd-bus-routing"]
    assert "dana%40example.org" in uri.path or "dana@example.org" in uri.path

    wrong = client.post("/auth/mfa/confirm", json={"code": "000000"})
    assert wrong.status_code == 400
    done = client.post("/auth/mfa/confirm", json={"code": _code(setup["secret"], clock)})
    assert done.status_code == 200, done.text
    body = done.json()
    assert len(body["recovery_codes"]) == 10 and len(set(body["recovery_codes"])) == 10
    assert client.cookies.get(MFA_PENDING_COOKIE_NAME) is None
    me = client.get("/users/me", headers=auth_headers(body["access_token"])).json()
    assert me["mfa_enabled"] is True and me["mfa_required"] is True
    assert client.get("/users/me").status_code == 200  # the session cookie too

    db_session.refresh(user)
    # Stored encrypted, and recovery codes only as hashes.
    assert setup["secret"] not in user.mfa_secret_encrypted
    assert mfa.decrypt(user.mfa_secret_encrypted) == setup["secret"]
    stored = [r.code_hash for r in db_session.query(MfaRecoveryCode).all()]
    assert not any(c.replace("-", "") in h for c in body["recovery_codes"] for h in stored)
    assert db_session.query(AuditLogEntry).filter_by(action="mfa_enabled").count() == 1


def test_signing_in_needs_a_fresh_code_each_time(client, db_session, clock, staff_need_mfa):
    make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    secret, _ = _enrol(client, clock)

    clock["t"] += 30
    assert _password_step(client)["mfa"] == "verify"
    code = _code(secret, clock)
    signed_in = client.post("/auth/mfa/verify", json={"code": code})
    assert signed_in.status_code == 200, signed_in.text
    assert (
        client.get("/users/me", headers=auth_headers(signed_in.json()["access_token"])).status_code
        == 200
    )

    # The same code can't be used again, even within its 30 seconds.
    _password_step(client)
    replay = client.post("/auth/mfa/verify", json={"code": code})
    assert replay.status_code == 400
    clock["t"] += 30
    assert client.post("/auth/mfa/verify", json={"code": _code(secret, clock)}).status_code == 200


def test_a_code_from_the_neighbouring_step_counts(client, db_session, clock, staff_need_mfa):
    make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    secret, _ = _enrol(client, clock)
    clock["t"] += 120
    _password_step(client)
    assert (
        client.post("/auth/mfa/verify", json={"code": _code(secret, clock, -2)}).status_code == 400
    )
    assert (
        client.post("/auth/mfa/verify", json={"code": _code(secret, clock, -1)}).status_code == 200
    )


def test_recovery_codes_work_once(client, db_session, clock, staff_need_mfa):
    make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    _, enrolled = _enrol(client, clock)
    code = enrolled["recovery_codes"][0]

    _password_step(client)
    used = client.post("/auth/mfa/verify", json={"code": code.lower().replace("-", " ")})
    assert used.status_code == 200, used.text
    assert used.json()["recovery_codes_left"] == 9
    entry = db_session.query(AuditLogEntry).filter_by(action="mfa_recovery_code_used").one()
    assert entry.after_state == {"recovery_codes_left": 9}

    _password_step(client)
    assert client.post("/auth/mfa/verify", json={"code": code}).status_code == 400


def test_new_recovery_codes_need_a_current_code(client, db_session, clock, staff_need_mfa):
    make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    secret, enrolled = _enrol(client, clock)
    headers = auth_headers(enrolled["access_token"])
    assert (
        client.post(
            "/auth/mfa/recovery-codes", headers=headers, json={"code": "123456"}
        ).status_code
        == 400
    )
    clock["t"] += 30
    fresh = client.post(
        "/auth/mfa/recovery-codes", headers=headers, json={"code": _code(secret, clock)}
    )
    assert fresh.status_code == 200
    assert set(fresh.json()["recovery_codes"]).isdisjoint(enrolled["recovery_codes"])
    status = client.get("/auth/mfa", headers=headers).json()
    assert status == {"allowed": True, "required": True, "enabled": True, "recovery_codes_left": 10}


def test_password_only_sessions_stop_working_for_roles_that_need_it(
    client, db_session, staff_need_mfa
):
    user = make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    token = create_access_token(user_id=user.id, role=user.role)
    refused = client.get("/users/me", headers=auth_headers(token))
    assert refused.status_code == 401
    assert refused.json()["detail"] == "Sign in again to use two-step sign-in."


def test_a_promotion_ends_password_only_sessions(client, db_session, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "mfa_required_roles", ["dispatcher"])
    user = make_user(db_session, email="pat@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="pat@example.org")
    client.patch(f"/users/{user.id}", headers=admin_headers, json={"role": "dispatcher"})
    assert client.get("/users/me", headers=auth_headers(token)).status_code == 401


def test_families_may_turn_it_on_and_off(client, db_session, clock, staff_need_mfa):
    make_user(db_session, email="pat@example.org", role=Role.PARENT)
    old = login(client, email="pat@example.org")  # no second step for families by default
    headers = auth_headers(old)
    assert client.get("/auth/mfa", headers=headers).json()["required"] is False

    setup = client.post("/auth/mfa/setup", headers=headers).json()
    turned_on = client.post(
        "/auth/mfa/confirm", headers=headers, json={"code": _code(setup["secret"], clock)}
    )
    assert turned_on.status_code == 200
    new = auth_headers(turned_on.json()["access_token"])
    assert client.get("/users/me", headers=headers).status_code == 401  # sessions from before end
    assert client.get("/users/me", headers=new).status_code == 200
    assert _password_step(client, "pat@example.org")["mfa"] == "verify"

    wrong = client.post("/auth/mfa/disable", headers=new, json={"password": "nope"})
    assert wrong.status_code == 400
    off = client.post("/auth/mfa/disable", headers=new, json={"password": "password123"})
    assert off.status_code == 200, off.text
    assert login(client, email="pat@example.org")
    assert db_session.query(AuditLogEntry).filter_by(action="mfa_disabled").count() == 1


def test_staff_cannot_turn_it_off(client, db_session, clock, staff_need_mfa):
    make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    _, enrolled = _enrol(client, clock)
    off = client.post(
        "/auth/mfa/disable",
        headers=auth_headers(enrolled["access_token"]),
        json={"password": "password123"},
    )
    assert off.status_code == 403


def test_drivers_never_use_it(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "mfa_required_roles", ["driver", "dispatcher"])
    make_user(db_session, email="drv@example.org", role=Role.DRIVER)
    token = login(client, email="drv@example.org")
    assert client.post("/auth/mfa/setup", headers=auth_headers(token)).status_code == 403


def test_admins_reset_someone_elses(client, db_session, clock, monkeypatch, admin_headers):
    monkeypatch.setattr(settings, "mfa_required_roles", ["dispatcher"])
    user = make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    _, enrolled = _enrol(client, clock)

    denied = client.post(
        f"/users/{user.id}/mfa-reset", headers=auth_headers(enrolled["access_token"])
    )
    assert denied.status_code == 403
    reset = client.post(f"/users/{user.id}/mfa-reset", headers=admin_headers)
    assert reset.status_code == 200, reset.text
    assert reset.json()["mfa_enabled"] is False
    assert (
        client.get("/users/me", headers=auth_headers(enrolled["access_token"])).status_code == 401
    )
    assert _password_step(client)["mfa"] == "setup"
    assert db_session.query(MfaRecoveryCode).count() == 0
    assert db_session.query(AuditLogEntry).filter_by(action="mfa_reset").one().entity_id == user.id

    assert client.post(f"/users/{user.id}/mfa-reset", headers=admin_headers).status_code == 409
    admin = db_session.query(User).filter_by(email="admin@example.org").one()
    own = client.post(f"/users/{admin.id}/mfa-reset", headers=admin_headers)
    assert own.status_code == 400


def test_verify_without_a_pending_sign_in(client):
    response = client.post("/auth/mfa/verify", json={"code": "123456"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Your sign-in timed out. Enter your password again."


def test_wrong_codes_are_rate_limited(client, db_session, clock, staff_need_mfa):
    make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    _enrol(client, clock)
    _password_step(client)
    codes = [
        client.post("/auth/mfa/verify", json={"code": "000000"}).status_code for _ in range(11)
    ]
    assert codes[-1] == 429


def test_production_needs_an_encryption_key():
    base = {"environment": "production", "jwt_secret_key": "x" * 40}
    with pytest.raises(RuntimeError, match="ISD_API_MFA_ENCRYPTION_KEY"):
        Settings(**base).require_production_ready()
    with pytest.raises(RuntimeError, match="ISD_API_MFA_ENCRYPTION_KEY"):
        Settings(**base, mfa_encryption_key="too-short").require_production_ready()
    Settings(**base, mfa_encryption_key=Fernet.generate_key().decode()).require_production_ready()
