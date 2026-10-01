"""Single sign-on with the district's identity provider (Phase 5.4).

Generic OpenID Connect (authorization code flow with PKCE), so Microsoft
Entra ID, Google Workspace, Keycloak and others all work through the
`ISD_API_OIDC_*` settings. Decisions by the product owner (2026-10-01):

- SSO only signs in accounts that already exist, matched on the email
  the provider vouches for; admins still create accounts and choose
  roles. Families keep passwords (`ISD_API_OIDC_ROLES` lists who may use
  it). The first sign-in links the provider's subject id to the account
  and later ones must match it, so a reassigned email can't take over.
- The provider's two-step check counts only when its ID token says one
  was used (`amr`/`acr`, `ISD_API_OIDC_TRUST_MFA=claim`); otherwise ours
  is asked for as after a password.
- Password sign-in stays available as a fallback.

No new dependencies: PyJWT (with `cryptography`) verifies the ID token
against the provider's published keys; HTTP uses the standard library.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import jwt

from isd_api.config import settings

TIMEOUT_SECONDS = 10
DISCOVERY_TTL_SECONDS = 3600
# Asymmetric signatures only: a provider's ID token is never HMAC or "none".
ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384"]
# `amr` values (RFC 8176) that mean a second factor was used.
MFA_AMR = {"mfa", "otp", "hwk", "swk", "sms", "fpt", "face", "iris", "sc", "pin"}

_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class OidcError(Exception):
    """Sign-in can't continue; `code` is shown to the person as a reason."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def is_configured() -> bool:
    return bool(
        settings.oidc_issuer
        and settings.oidc_client_id
        and settings.oidc_client_secret
        and settings.oidc_redirect_uri
    )


def http_json(url: str, form: dict[str, str] | None = None) -> dict[str, Any]:
    """GET (or POST a form to) `url` and parse the JSON reply."""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(url, data=data, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def discovery() -> dict[str, Any]:
    issuer = (settings.oidc_issuer or "").rstrip("/")
    cached = _discovery_cache.get(issuer)
    if cached and time.time() - cached[0] < DISCOVERY_TTL_SECONDS:
        return cached[1]
    try:
        document = http_json(f"{issuer}/.well-known/openid-configuration")
    except (OSError, ValueError) as exc:
        raise OidcError("provider_unreachable", str(exc)) from exc
    if document.get("issuer", "").rstrip("/") != issuer:
        raise OidcError("failed", "the provider's discovery document names another issuer")
    _discovery_cache[issuer] = (time.time(), document)
    return document


def clear_cache() -> None:
    _discovery_cache.clear()


@dataclass(frozen=True)
class Start:
    url: str
    state: str
    nonce: str
    verifier: str


def start() -> Start:
    """Where to send the browser, plus what to remember until it's back."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id or "",
        "redirect_uri": settings.oidc_redirect_uri or "",
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge.decode().rstrip("="),
        "code_challenge_method": "S256",
    }
    url = f"{discovery()['authorization_endpoint']}?{urllib.parse.urlencode(params)}"
    return Start(url=url, state=state, nonce=nonce, verifier=verifier)


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str
    mfa_used: bool


def _signing_key(id_token: str, jwks_uri: str) -> Any:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise OidcError("failed", "unreadable ID token") from exc
    if header.get("alg") not in ALLOWED_ALGORITHMS:
        raise OidcError("failed", f"ID token signed with {header.get('alg')!r}")
    try:
        keys = http_json(jwks_uri).get("keys", [])
    except (OSError, ValueError) as exc:
        raise OidcError("provider_unreachable", str(exc)) from exc
    for key in keys:
        if header.get("kid") is None or key.get("kid") == header.get("kid"):
            try:
                return jwt.PyJWK(key, algorithm=header["alg"]).key
            except jwt.PyJWTError:
                continue
    raise OidcError("failed", "no matching signing key")


def _mfa_used(claims: dict[str, Any]) -> bool:
    mode = settings.oidc_trust_mfa
    if mode == "always":
        return True
    if mode == "never":
        return False
    amr = claims.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    if any(str(value).lower() in MFA_AMR for value in amr):
        return True
    return claims.get("acr") in settings.oidc_mfa_acr_values


def finish(code: str, nonce: str, verifier: str) -> Identity:
    """Exchanges the code for tokens and checks the ID token fully."""
    document = discovery()
    try:
        tokens = http_json(
            document["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri or "",
                "client_id": settings.oidc_client_id or "",
                "client_secret": settings.oidc_client_secret or "",
                "code_verifier": verifier,
            },
        )
    except (OSError, ValueError) as exc:
        raise OidcError("failed", f"token exchange failed: {exc}") from exc
    id_token = tokens.get("id_token")
    if not isinstance(id_token, str):
        raise OidcError("failed", "no ID token in the reply")
    try:
        claims = jwt.decode(
            id_token,
            _signing_key(id_token, document["jwks_uri"]),
            algorithms=ALLOWED_ALGORITHMS,
            audience=settings.oidc_client_id,
            issuer=document["issuer"],
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise OidcError("failed", f"ID token rejected: {exc}") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError("failed", "ID token nonce doesn't match")
    email = claims.get(settings.oidc_email_claim)
    if not isinstance(email, str) or "@" not in email:
        raise OidcError("no_email", "the provider sent no email address")
    if claims.get("email_verified") is False:
        raise OidcError("no_email", "the provider says the email isn't verified")
    return Identity(
        subject=str(claims["sub"]), email=email.strip().lower(), mfa_used=_mfa_used(claims)
    )
