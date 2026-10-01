import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from isd_api import oidc
from isd_api.config import Settings, settings
from isd_api.models import AuditLogEntry, Role, User
from isd_api.security import MFA_PENDING_COOKIE_NAME, SESSION_COOKIE_NAME
from tests.conftest import make_user

ISSUER = "https://idp.example.test/realms/district"
CLIENT_ID = "isd-bus-routing"
WEB = "http://web.example.test"


def _key(kid):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update(kid=kid, alg="RS256", use="sig")
    return private, jwk


SIGNING_KEY, SIGNING_JWK = _key("k1")
OTHER_KEY, _ = _key("k2")


class FakeProvider:
    """The district's identity provider, as the api sees it over HTTP."""

    def __init__(self):
        self.claims = {}
        self.nonce = None
        self.token_form = None
        self.sign_with = SIGNING_KEY
        self.algorithm = "RS256"
        self.kid = "k1"
        self.force_nonce = None

    def http_json(self, url, form=None):
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return {
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/auth",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/certs",
            }
        if url == f"{ISSUER}/certs":
            return {"keys": [SIGNING_JWK]}
        if url == f"{ISSUER}/token":
            self.token_form = form
            now = int(time.time())
            claims = {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "sub": "district-sub-1",
                "iat": now,
                "exp": now + 300,
                "nonce": self.force_nonce or self.nonce,
                "email": "dana@example.org",
                "email_verified": True,
                **self.claims,
            }
            claims = {k: v for k, v in claims.items() if v is not None}
            key = self.sign_with if self.algorithm != "HS256" else "x" * 32
            token = jwt.encode(claims, key, algorithm=self.algorithm, headers={"kid": self.kid})
            return {"access_token": "at", "id_token": token, "token_type": "Bearer"}
        raise AssertionError(f"unexpected request to {url}")


@pytest.fixture()
def provider(monkeypatch):
    fake = FakeProvider()
    oidc.clear_cache()
    monkeypatch.setattr(oidc, "http_json", fake.http_json)
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "oidc_client_secret", "client-secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "http://testserver/auth/oidc/callback")
    monkeypatch.setattr(settings, "oidc_trust_mfa", "claim")
    monkeypatch.setattr(settings, "oidc_mfa_acr_values", [])
    monkeypatch.setattr(settings, "public_web_url", WEB)
    yield fake
    oidc.clear_cache()


def _sign_in(client, provider, **query):
    start = client.get("/auth/oidc/start", follow_redirects=False)
    assert start.status_code == 303, start.text
    params = {k: v[0] for k, v in parse_qs(urlparse(start.headers["location"]).query).items()}
    provider.nonce = params["nonce"]
    callback = {"code": "the-code", "state": params["state"], **query}
    response = client.get("/auth/oidc/callback", params=callback, follow_redirects=False)
    assert response.status_code == 303, response.text
    return params, response.headers["location"]


def test_the_start_sends_the_browser_to_the_provider_with_pkce(client, provider):
    start = client.get("/auth/oidc/start", follow_redirects=False)
    url = urlparse(start.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{ISSUER}/auth"
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert params["client_id"] == CLIENT_ID
    assert params["response_type"] == "code"
    assert params["code_challenge_method"] == "S256"
    assert params["scope"] == "openid email profile"
    assert len(params["state"]) > 30 and len(params["nonce"]) > 30
    assert client.cookies.get("isd_oidc")


def test_an_existing_account_signs_in_and_is_linked(client, db_session, provider, monkeypatch):
    monkeypatch.setattr(settings, "mfa_required_roles", ["dispatcher"])
    user = make_user(db_session, email="Dana@Example.org", role=Role.DISPATCHER)
    provider.claims = {"amr": ["pwd", "mfa"]}
    params, location = _sign_in(client, provider)

    assert location == f"{WEB}/"
    assert client.cookies.get(SESSION_COOKIE_NAME)
    me = client.get("/users/me")
    assert me.status_code == 200 and me.json()["sso_linked"] is True
    db_session.refresh(user)
    assert user.oidc_subject == "district-sub-1"
    assert db_session.query(AuditLogEntry).filter_by(action="sso_linked").count() == 1
    # PKCE: the verifier sent to the token endpoint matches the challenge.
    verifier = provider.token_form["code_verifier"]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert challenge == params["code_challenge"]
    assert provider.token_form["client_secret"] == "client-secret"


def test_without_the_providers_mfa_ours_is_asked_for(client, db_session, provider, monkeypatch):
    monkeypatch.setattr(settings, "mfa_required_roles", ["dispatcher"])
    make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    provider.claims = {"amr": ["pwd"]}
    _, location = _sign_in(client, provider)
    assert location == f"{WEB}/login?mfa=setup"
    assert client.cookies.get(MFA_PENDING_COOKIE_NAME)
    assert client.cookies.get(SESSION_COOKIE_NAME) is None
    assert client.post("/auth/mfa/setup").status_code == 200


@pytest.mark.parametrize(
    ("mode", "claims", "trusted"),
    [
        ("claim", {"acr": "gold"}, True),
        ("claim", {"acr": "silver"}, False),
        ("always", {}, True),
        ("never", {"amr": ["mfa"]}, False),
    ],
)
def test_how_far_the_providers_mfa_is_trusted(
    client, db_session, provider, monkeypatch, mode, claims, trusted
):
    monkeypatch.setattr(settings, "mfa_required_roles", ["dispatcher"])
    monkeypatch.setattr(settings, "oidc_trust_mfa", mode)
    monkeypatch.setattr(settings, "oidc_mfa_acr_values", ["gold"])
    make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    provider.claims = claims
    _, location = _sign_in(client, provider)
    assert location == (f"{WEB}/" if trusted else f"{WEB}/login?mfa=setup")


def test_roles_without_mfa_just_sign_in(client, db_session, provider):
    make_user(db_session, email="dana@example.org", role=Role.DRIVER)
    _, location = _sign_in(client, provider)
    assert location == f"{WEB}/"
    assert client.get("/users/me").status_code == 200


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ({"email": "nobody@example.org"}, "no_account"),
        ({"role": Role.PARENT}, "not_for_role"),
        ({"is_active": False}, "no_account"),
    ],
)
def test_who_cannot_sign_in(client, db_session, provider, setup, reason):
    make_user(
        db_session,
        email=setup.get("email", "dana@example.org"),
        role=setup.get("role", Role.DISPATCHER),
        is_active=setup.get("is_active", True),
    )
    provider.claims = {"email": "dana@example.org"}
    _, location = _sign_in(client, provider)
    assert location == f"{WEB}/login?sso_error={reason}"
    assert client.cookies.get(SESSION_COOKIE_NAME) is None


def test_a_reassigned_email_cannot_take_over(client, db_session, provider, admin_headers):
    user = make_user(db_session, email="dana@example.org", role=Role.DRIVER)
    user.oidc_subject = "the-original-person"
    db_session.commit()
    _, location = _sign_in(client, provider)
    assert location == f"{WEB}/login?sso_error=linked_elsewhere"

    unlinked = client.post(f"/users/{user.id}/sso-unlink", headers=admin_headers)
    assert unlinked.status_code == 200 and unlinked.json()["sso_linked"] is False
    assert db_session.query(AuditLogEntry).filter_by(action="sso_unlinked").count() == 1
    client.cookies.clear()
    _, location = _sign_in(client, provider)
    assert location == f"{WEB}/"


def test_one_district_account_links_to_one_user(client, db_session, provider):
    other = make_user(db_session, email="other@example.org", role=Role.DRIVER)
    other.oidc_subject = "district-sub-1"
    db_session.commit()
    make_user(db_session, email="dana@example.org", role=Role.DRIVER)
    _, location = _sign_in(client, provider)
    assert location == f"{WEB}/login?sso_error=linked_elsewhere"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"claims": {"aud": "someone-else"}}, "failed"),
        ({"claims": {"iss": "https://evil.example.test"}}, "failed"),
        ({"force_nonce": "replayed"}, "failed"),
        ({"claims": {"exp": 1}}, "failed"),
        ({"sign_with": OTHER_KEY}, "failed"),
        ({"algorithm": "HS256"}, "failed"),
        ({"claims": {"email_verified": False}}, "no_email"),
        ({"claims": {"email": None}}, "no_email"),
    ],
)
def test_bad_id_tokens_are_refused(client, db_session, provider, change, reason):
    make_user(db_session, email="dana@example.org", role=Role.DRIVER)
    for name, value in change.items():
        setattr(provider, name, value)
    _, location = _sign_in(client, provider)
    assert location == f"{WEB}/login?sso_error={reason}"
    assert client.cookies.get(SESSION_COOKIE_NAME) is None


def test_state_must_match_and_be_recent(client, db_session, provider):
    make_user(db_session, email="dana@example.org", role=Role.DRIVER)
    client.get("/auth/oidc/start", follow_redirects=False)
    forged = client.get(
        "/auth/oidc/callback", params={"code": "c", "state": "forged"}, follow_redirects=False
    )
    assert forged.headers["location"] == f"{WEB}/login?sso_error=expired"

    client.cookies.clear()
    no_cookie = client.get(
        "/auth/oidc/callback", params={"code": "c", "state": "s"}, follow_redirects=False
    )
    assert no_cookie.headers["location"] == f"{WEB}/login?sso_error=expired"

    cancelled = client.get(
        "/auth/oidc/callback", params={"error": "access_denied"}, follow_redirects=False
    )
    assert cancelled.headers["location"] == f"{WEB}/login?sso_error=cancelled"


def test_off_unless_configured(client, provider, monkeypatch):
    assert client.get("/auth/options").json()["sso_label"] == "your district account"
    monkeypatch.setattr(settings, "oidc_issuer", None)
    assert client.get("/auth/options").json()["sso_label"] is None
    assert client.get("/auth/oidc/start", follow_redirects=False).status_code == 404


def test_settings_need_the_whole_client(monkeypatch):
    with pytest.raises(RuntimeError, match="ISD_API_OIDC_CLIENT_SECRET"):
        Settings(
            oidc_issuer=ISSUER, oidc_client_id="x", oidc_redirect_uri="https://a/cb"
        ).require_production_ready()
    full = {"oidc_client_id": "x", "oidc_client_secret": "y", "oidc_redirect_uri": "https://a/cb"}
    Settings(oidc_issuer=ISSUER, **full).require_production_ready()
    with pytest.raises(RuntimeError, match="https://"):
        Settings(
            environment="production",
            jwt_secret_key="x" * 40,
            mfa_encryption_key=base64.urlsafe_b64encode(b"k" * 32).decode(),
            oidc_issuer="http://idp.example.test",
            **full,
        ).require_production_ready()


def test_password_sign_in_still_works_for_linked_staff(client, db_session, provider):
    user = make_user(db_session, email="dana@example.org", role=Role.DRIVER)
    user.oidc_subject = "district-sub-1"
    db_session.commit()
    response = client.post(
        "/auth/login", data={"username": "dana@example.org", "password": "password123"}
    )
    assert response.status_code == 200 and response.json()["access_token"]
    assert db_session.get(User, user.id).sso_linked
