"""Two-step sign-in endpoints (Phase 5.3); the rules are in isd_api/mfa.py.

During sign-in, after a correct password, these work from the short-lived
pending cookie (security.set_mfa_pending_cookie); from the Account page
they work from the normal session.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from isd_api import account_emails, mailer, mfa
from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import User
from isd_api.schemas import (
    LoginResult,
    MfaCode,
    MfaConfirmRead,
    MfaDisable,
    MfaSetupRead,
    MfaStatus,
    RecoveryCodesRead,
)
from isd_api.security import (
    MFA_PENDING_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    clear_mfa_pending_cookie,
    get_current_user,
    issue_tokens,
    oauth2_scheme,
    password_rate_limiter,
    pending_mfa_user,
    verify_password,
)

router = APIRouter(prefix="/auth/mfa", tags=["auth"])

TIMED_OUT = "Your sign-in timed out. Enter your password again."
WRONG_CODE = "That code didn't work. Enter the newest code from your authenticator app."


def _actor(
    response: Response,
    db: Session,
    pending: str | None,
    bearer: str | None,
    session: str | None,
) -> tuple[User, bool]:
    """The person setting up two-step sign-in, and whether they're mid
    sign-in (pending cookie) rather than signed in."""
    user = pending_mfa_user(pending, db)
    if user is not None:
        return user, True
    if bearer is None and session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=TIMED_OUT)
    return get_current_user(response, bearer, session, db), False


def _notify(background: BackgroundTasks, email: mailer.Email) -> None:
    if mailer.is_configured():
        background.add_task(mailer.send_quietly, email)


@router.get("", response_model=MfaStatus)
def mfa_status(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> MfaStatus:
    return MfaStatus(
        allowed=mfa.is_allowed(current_user),
        required=mfa.is_required(current_user),
        enabled=mfa.is_enabled(current_user),
        recovery_codes_left=mfa.recovery_codes_left(db, current_user),
    )


@router.post("/setup", response_model=MfaSetupRead)
def mfa_setup(
    response: Response,
    db: Session = Depends(get_db),
    pending: str | None = Cookie(default=None, alias=MFA_PENDING_COOKIE_NAME),
    bearer: str | None = Depends(oauth2_scheme),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> MfaSetupRead:
    """Starts setup: a new secret, not in force until /confirm gets a
    matching code. Calling it again starts over with a new one."""
    user, _ = _actor(response, db, pending, bearer, session)
    if not mfa.is_allowed(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Two-step sign-in isn't used on driver accounts",
        )
    if mfa.is_enabled(user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Two-step sign-in is already on"
        )
    secret = mfa.new_secret()
    user.mfa_pending_secret_encrypted = mfa.encrypt(secret)
    db.commit()
    return MfaSetupRead(secret=secret, otpauth_uri=mfa.otpauth_uri(secret, user.email))


@router.post("/confirm", response_model=MfaConfirmRead)
def mfa_confirm(
    payload: MfaCode,
    response: Response,
    db: Session = Depends(get_db),
    pending: str | None = Cookie(default=None, alias=MFA_PENDING_COOKIE_NAME),
    bearer: str | None = Depends(oauth2_scheme),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> MfaConfirmRead:
    """Turns two-step sign-in on once a code from the new secret matches;
    returns the recovery codes (shown once) and signs the person in."""
    user, _ = _actor(response, db, pending, bearer, session)
    password_rate_limiter.check(f"mfa:{user.id}")
    if user.mfa_pending_secret_encrypted is None or mfa.is_enabled(user):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start the setup again")
    step = mfa.matching_step(mfa.decrypt(user.mfa_pending_secret_encrypted), payload.code, None)
    if step is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That code didn't match. Check your phone's clock is set automatically, "
            "then enter the newest code.",
        )
    user.mfa_secret_encrypted = user.mfa_pending_secret_encrypted
    user.mfa_pending_secret_encrypted = None
    user.mfa_last_step = step
    user.mfa_enabled_at = datetime.now(UTC)
    codes = mfa.new_recovery_codes(db, user)
    record_audit(db, entity_type="user", entity_id=user.id, action="mfa_enabled", actor=user)
    db.commit()
    db.refresh(user)
    clear_mfa_pending_cookie(response)
    return MfaConfirmRead(access_token=issue_tokens(response, user, mfa=True), recovery_codes=codes)


@router.post("/verify", response_model=LoginResult)
def mfa_verify(
    payload: MfaCode,
    response: Response,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    pending: str | None = Cookie(default=None, alias=MFA_PENDING_COOKIE_NAME),
) -> LoginResult:
    """The second step of signing in: a code from the authenticator app,
    or one of the recovery codes."""
    user = pending_mfa_user(pending, db)
    if user is None or not mfa.is_enabled(user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=TIMED_OUT)
    password_rate_limiter.check(f"mfa:{user.id}")
    left: int | None = None
    if not mfa.verify_code(user, payload.code):
        if not mfa.use_recovery_code(db, user, payload.code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=WRONG_CODE)
        db.flush()
        left = mfa.recovery_codes_left(db, user)
        record_audit(
            db,
            entity_type="user",
            entity_id=user.id,
            action="mfa_recovery_code_used",
            actor=user,
            after_state={"recovery_codes_left": left},
        )
        _notify(background, account_emails.recovery_code_used_email(user, left))
    db.commit()
    db.refresh(user)
    clear_mfa_pending_cookie(response)
    return LoginResult(
        access_token=issue_tokens(response, user, mfa=True), recovery_codes_left=left
    )


@router.post("/recovery-codes", response_model=RecoveryCodesRead)
def replace_recovery_codes(
    payload: MfaCode,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecoveryCodesRead:
    """New recovery codes (the old ones stop working); needs a current
    code from the authenticator app."""
    password_rate_limiter.check(f"mfa:{current_user.id}")
    if not mfa.verify_code(current_user, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=WRONG_CODE)
    codes = mfa.new_recovery_codes(db, current_user)
    record_audit(
        db,
        entity_type="user",
        entity_id=current_user.id,
        action="mfa_recovery_codes_replaced",
        actor=current_user,
    )
    db.commit()
    return RecoveryCodesRead(recovery_codes=codes)


@router.post("/disable", response_model=LoginResult)
def mfa_disable(
    payload: MfaDisable,
    response: Response,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LoginResult:
    """Turns it off, for roles that don't need it; needs the password."""
    password_rate_limiter.check(f"mfa:{current_user.id}")
    if mfa.is_required(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role needs two-step sign-in, so it can't be turned off",
        )
    if not mfa.is_enabled(current_user):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="It's already off")
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Your password is incorrect"
        )
    mfa.turn_off(db, current_user)
    record_audit(
        db, entity_type="user", entity_id=current_user.id, action="mfa_disabled", actor=current_user
    )
    db.commit()
    db.refresh(current_user)
    _notify(background, account_emails.mfa_turned_off_email(current_user))
    return LoginResult(access_token=issue_tokens(response, current_user))
