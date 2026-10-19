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


def test_login_sets_httponly_session_cookie_with_correct_flags(client, db_session):
    make_user(db_session, email="a@example.org", role=Role.DISPATCHER, password="correct-horse")
    response = client.post(
        "/auth/login", data={"username": "a@example.org", "password": "correct-horse"}
    )
    assert response.status_code == 200
    assert "isd_session" in response.cookies

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie_header
    assert "samesite=lax" in set_cookie_header.lower()
    # Test config runs with environment != "production", so Secure must
    # be absent — it would make the cookie unusable over plain HTTP.
    assert "Secure" not in set_cookie_header


def test_protected_endpoint_reachable_via_session_cookie_alone(client, db_session):
    make_user(db_session, email="a@example.org", role=Role.DISPATCHER, password="correct-horse")
    login_response = client.post(
        "/auth/login", data={"username": "a@example.org", "password": "correct-horse"}
    )
    assert login_response.status_code == 200

    # No Authorization header at all — only the cookie the client's jar
    # picked up from the login response above.
    response = client.get("/users/me")
    assert response.status_code == 200
    assert response.json()["email"] == "a@example.org"


def test_cookie_authenticated_request_renews_the_cookie(client, db_session):
    make_user(db_session, email="a@example.org", role=Role.DISPATCHER, password="correct-horse")
    client.post("/auth/login", data={"username": "a@example.org", "password": "correct-horse"})

    response = client.get("/users/me")
    assert response.status_code == 200
    assert "isd_session" in response.cookies  # renewed, not just relied upon


def test_logout_clears_the_session_cookie(client, db_session):
    make_user(db_session, email="a@example.org", role=Role.DISPATCHER, password="correct-horse")
    client.post("/auth/login", data={"username": "a@example.org", "password": "correct-horse"})

    logout_response = client.post("/auth/logout")
    assert logout_response.status_code == 204

    # The cookie is gone from the client's jar, so a cookie-only request
    # now fails the same way it would for someone who never logged in.
    response = client.get("/users/me")
    assert response.status_code == 401


def test_login_rate_limits_after_too_many_failed_attempts(client, db_session):
    make_user(db_session, email="a@example.org", role=Role.DISPATCHER, password="correct-horse")

    from isd_api.config import settings

    for _ in range(settings.login_rate_limit_attempts):
        response = client.post(
            "/auth/login", data={"username": "a@example.org", "password": "wrong-guess"}
        )
        assert response.status_code == 401

    # One more within the same window, even with fully correct
    # credentials, must be rejected as too many attempts, not logged in.
    over_limit = client.post(
        "/auth/login", data={"username": "a@example.org", "password": "correct-horse"}
    )
    assert over_limit.status_code == 429


def test_successful_sign_ins_from_one_address_never_lock_it_out(client, db_session):
    """A depot's drivers all sign in from one Wi-Fi (one address) at 6am."""
    from isd_api.config import settings

    for n in range(settings.login_rate_limit_attempts * 3):
        make_user(db_session, email=f"driver{n}@example.org", role=Role.DRIVER, password="pw-12345")
        response = client.post(
            "/auth/login", data={"username": f"driver{n}@example.org", "password": "pw-12345"}
        )
        assert response.status_code == 200


def test_login_under_the_limit_is_unaffected(client, db_session):
    make_user(db_session, email="a@example.org", role=Role.DISPATCHER, password="correct-horse")
    response = client.post(
        "/auth/login", data={"username": "a@example.org", "password": "correct-horse"}
    )
    assert response.status_code == 200


def test_logout_revokes_the_token_server_side_not_just_the_cookie(client, db_session):
    """Distinct from test_logout_clears_the_session_cookie: that test
    reuses the same client/cookie-jar, so it can't tell "cookie cleared
    client-side" apart from "token actually revoked server-side." This
    test captures the raw token value before logout and presents it
    directly afterwards — the only way to prove revocation happened."""
    make_user(db_session, email="a@example.org", role=Role.DISPATCHER, password="correct-horse")
    login_response = client.post(
        "/auth/login", data={"username": "a@example.org", "password": "correct-horse"}
    )
    captured_session_cookie = login_response.cookies["isd_session"]

    logout_response = client.post("/auth/logout")
    assert logout_response.status_code == 204

    # Present the captured (pre-logout) token directly as a bearer
    # token — bypasses the client's own (now-cleared) cookie jar
    # entirely, so this can only succeed if the token itself is still
    # valid server-side.
    replayed = client.get("/users/me", headers=auth_headers(captured_session_cookie))
    assert replayed.status_code == 401
    assert "revoked" in replayed.json()["detail"].lower()


def test_logout_with_no_session_still_succeeds(client):
    response = client.post("/auth/logout")
    assert response.status_code == 204


def test_bearer_header_takes_priority_over_a_stale_cookie(client, db_session):
    """A client carrying an old session cookie alongside an explicit
    Authorization header for a *different* user must be authenticated
    as the header's user, not silently re-authenticated via the cookie —
    this is what test RBAC fixtures rely on throughout this test suite."""
    make_user(db_session, email="a@example.org", role=Role.DISPATCHER, password="correct-horse")
    make_user(
        db_session, email="b@example.org", role=Role.TRANSPORTATION_ADMIN, password="other-pw"
    )
    client.post("/auth/login", data={"username": "a@example.org", "password": "correct-horse"})
    token_b = login(client, email="b@example.org", password="other-pw")

    response = client.get("/users/me", headers=auth_headers(token_b))
    assert response.status_code == 200
    assert response.json()["email"] == "b@example.org"
