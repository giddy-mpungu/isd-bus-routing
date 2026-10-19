"""Single sign-on endpoints (Phase 5.4); the protocol is in isd_api/oidc.py.

The browser goes /auth/oidc/start -> the district's sign-in page ->
/auth/oidc/callback, which signs the person in (or asks for our two-step
code) and sends them back to the web app. Every outcome is a redirect;
a failure lands on /login?sso_error=<reason>.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from isd_api import mfa, oidc
from isd_api.audit import record as record_audit
from isd_api.config import settings
from isd_api.db import get_db
from isd_api.models import User
from isd_api.security import issue_tokens, login_rate_limiter, set_mfa_pending_cookie

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/oidc", tags=["auth"])

STATE_COOKIE_NAME = "isd_oidc"
STATE_MINUTES = 10


def _require_configured() -> None:
    if not oidc.is_configured():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Single sign-on is off")


def _to_web(path: str) -> RedirectResponse:
    response = RedirectResponse(f"{settings.web_url}{path}", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(STATE_COOKIE_NAME, path="/")
    return response


def _failed(reason: str) -> RedirectResponse:
    return _to_web(f"/login?sso_error={reason}")


@router.get("/start")
def oidc_start() -> RedirectResponse:
    """Sends the browser to the district's sign-in page. The state, nonce
    and PKCE verifier wait in a signed, 10-minute, httpOnly cookie."""
    _require_configured()
    try:
        begin = oidc.start()
    except oidc.OidcError as exc:
        logger.warning("SSO start failed: %s", exc)
        return _failed(exc.code)
    remembered = jwt.encode(
        {
            "purpose": "oidc",
            "state": begin.state,
            "nonce": begin.nonce,
            "verifier": begin.verifier,
            "exp": datetime.now(UTC) + timedelta(minutes=STATE_MINUTES),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    response = RedirectResponse(begin.url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        STATE_COOKIE_NAME,
        remembered,
        max_age=STATE_MINUTES * 60,
        httponly=True,
        # Lax, not Strict: the provider's redirect back is a top-level
        # navigation from another site, which must still carry it.
        samesite="lax",
        secure=settings.environment == "production",
        path="/",
    )
    return response


@router.get("/callback")
def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    remembered: str | None = Cookie(default=None, alias=STATE_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _require_configured()
    if error is not None:
        return _failed("cancelled")
    try:
        saved = jwt.decode(
            remembered or "", settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return _failed("expired")
    if (
        saved.get("purpose") != "oidc"
        or code is None
        or state is None
        or not secrets.compare_digest(state, str(saved.get("state", "")))
    ):
        return _failed("expired")
    # The provider checked the password; what's counted here is a code it
    # won't accept (forged or replayed), as a failed sign-in from this address.
    caller = request.client.host if request.client else "unknown"
    login_rate_limiter.check_failures(caller)
    try:
        identity = oidc.finish(code, str(saved["nonce"]), str(saved["verifier"]))
    except oidc.OidcError as exc:
        login_rate_limiter.count_failure(caller)
        logger.warning("SSO sign-in failed: %s", exc)
        return _failed(exc.code)

    user = db.query(User).filter(func.lower(User.email) == identity.email).first()
    if user is None or not user.is_active:
        return _failed("no_account")
    if user.role.value not in settings.oidc_roles:
        return _failed("not_for_role")
    if user.oidc_subject is None:
        taken = db.query(User).filter(User.oidc_subject == identity.subject).first()
        if taken is not None:
            return _failed("linked_elsewhere")
        user.oidc_subject = identity.subject
        record_audit(db, entity_type="user", entity_id=user.id, action="sso_linked", actor=user)
        db.commit()
        db.refresh(user)
    elif not secrets.compare_digest(user.oidc_subject, identity.subject):
        # The email now belongs to a different district account.
        return _failed("linked_elsewhere")

    needs_ours = (mfa.is_enabled(user) or mfa.is_required(user)) and not identity.mfa_used
    if needs_ours:
        response = _to_web(f"/login?mfa={'verify' if mfa.is_enabled(user) else 'setup'}")
        set_mfa_pending_cookie(response, user)
        return response
    response = _to_web("/")
    issue_tokens(response, user, mfa=identity.mfa_used)
    return response
