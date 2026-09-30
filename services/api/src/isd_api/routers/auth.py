from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from isd_api import passwords
from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import PasswordResetToken, User
from isd_api.schemas import PasswordChange, PasswordReset, Token
from isd_api.security import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    get_current_user,
    hash_password,
    issue_tokens,
    login_rate_limiter,
    oauth2_scheme,
    password_rate_limiter,
    revoke_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    login_rate_limiter.check(request.client.host if request.client else "unknown")
    user = db.query(User).filter(User.email == form_data.username).one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(form_data.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Two independent tokens for two independent purposes (Phase 3
    # plan): a short-lived bearer token for API/script/Swagger use
    # (returned in the body, unchanged from before), and a longer-lived
    # session token for the browser (set as an httpOnly cookie, never
    # exposed in the response body — the frontend never touches it).
    return Token(access_token=issue_tokens(response, user))


def _set_password(user: User, new_password: str) -> None:
    problem = passwords.policy_problem(new_password, user.email)
    if problem is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=problem)
    user.hashed_password = hash_password(new_password)
    # Ends every session issued before now (security.get_current_user).
    user.token_version += 1


@router.post("/change-password", response_model=Token)
def change_password(
    payload: PasswordChange,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Token:
    """Any signed-in user changes their own password. Other sessions end;
    this one gets fresh tokens so the person stays signed in."""
    password_rate_limiter.check(f"change:{current_user.id}")
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Your current password is incorrect"
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a password different from your current one",
        )
    _set_password(current_user, payload.new_password)
    record_audit(
        db,
        entity_type="user",
        entity_id=current_user.id,
        action="password_changed",
        actor=current_user,
    )
    db.commit()
    db.refresh(current_user)
    return Token(access_token=issue_tokens(response, current_user))


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    payload: PasswordReset,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """Sets a new password from a one-time reset link (isd_api/passwords.py).
    No sign-in needed; the person signs in afterwards with the new one."""
    password_rate_limiter.check(f"reset:{request.client.host if request.client else 'unknown'}")
    token = passwords.redeem_reset_token(db, payload.token)
    user = db.get(User, token.user_id) if token is not None else None
    if token is None or user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link has expired or was already used. Ask for a new one.",
        )
    _set_password(user, payload.new_password)
    token.used_at = datetime.now(UTC)
    # Any other links for the account stop working too.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.id != token.id,
    ).delete()
    record_audit(db, entity_type="user", entity_id=user.id, action="password_reset", actor=user)
    db.commit()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    bearer_token: str | None = Depends(oauth2_scheme),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> None:
    """No auth required — calling this with no session, or a garbage
    token, must keep succeeding harmlessly (a caller with nothing to
    log out of still wants a clean 204). When a real token *is*
    present, revoke it server-side (ADR 0006 follow-up) — clearing the
    cookie alone doesn't stop a captured token from staying valid until
    its natural expiry."""
    token = bearer_token or session_cookie
    if token is not None:
        revoke_token(db, token)
    clear_session_cookie(response)
