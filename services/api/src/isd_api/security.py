"""Auth primitives: password hashing, JWT issuance/verification, and
the FastAPI dependencies that enforce RBAC (spec section 17).

Uses the `bcrypt` library directly rather than passlib — passlib's
bcrypt backend has a known compatibility break with bcrypt>=4.1 (it
probes for a `__about__.__version__` attribute bcrypt no longer
ships), so calling bcrypt directly is the more reliable choice here.
"""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from isd_api.config import settings
from isd_api.db import get_db
from isd_api.models import RevokedToken, Role, User

# auto_error=False: a missing Authorization header must fall through to
# checking the session cookie (get_current_user below), not hard-fail
# before that check runs.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

SESSION_COOKIE_NAME = "isd_session"


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# Stored for an account whose owner hasn't chosen a password yet (a
# set-up email is on its way); no password matches it.
UNUSABLE_PASSWORD = "!unset"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if hashed_password == UNUSABLE_PASSWORD:
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(
    *,
    user_id: int,
    role: Role,
    token_version: int = 0,
    expires_delta: timedelta | None = None,
) -> str:
    delta = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    expire = datetime.now(UTC) + delta
    # jti (JWT ID): a unique identifier for this specific token, distinct
    # from its content — lets revoke_token() invalidate one issued token
    # by identity rather than needing to enumerate/compare its claims.
    # tv: the account's token_version when issued; a password change
    # bumps it, which ends every older session (get_current_user).
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "exp": expire,
        "jti": str(uuid.uuid4()),
        "tv": token_version,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_session_token(*, user_id: int, role: Role, token_version: int = 0) -> str:
    """A longer-lived token for the browser session cookie (Phase 3).
    Its exp is the absolute session ceiling — unaffected by the sliding
    Max-Age renewal set_session_cookie performs on each request."""
    return create_access_token(
        user_id=user_id,
        role=role,
        token_version=token_version,
        expires_delta=timedelta(hours=settings.session_absolute_max_hours),
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_inactivity_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def revoke_token(db: Session, token: str) -> None:
    """Invalidates one already-issued token server-side (POST
    /auth/logout) — clearing the browser's cookie alone doesn't stop a
    captured token from remaining valid until its natural expiry.
    Decodes leniently: a missing/garbage/already-expired token is a
    no-op, not an error, since logout must stay callable with no
    session at all (its existing, still-true contract)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti is None or exp is None:
        return
    if db.get(RevokedToken, jti) is None:
        db.add(RevokedToken(jti=jti, expires_at=datetime.fromtimestamp(exp, tz=UTC)))
    # Opportunistic cleanup: a revoked token past its own natural expiry
    # no longer needs a denylist entry (get_current_user would already
    # reject it as expired) — keeps this table from growing unbounded
    # without a separate scheduled job.
    db.query(RevokedToken).filter(RevokedToken.expires_at < datetime.now(UTC)).delete()
    db.commit()


class LoginRateLimiter:
    """In-memory, per-process fixed-window limiter for POST /auth/login
    (ADR 0006 follow-up: brute-force/credential-stuffing protection).
    Counts all attempts — success or failure — per key within the
    window; simpler than fail-only counting and still stops a
    hammering script.

    Deliberately in-process, not shared storage: this project's current
    deployment (docker-compose.yml) runs a single uvicorn process with
    no reverse proxy in front of it, so per-process state and
    `request.client.host` both reflect the real caller. A future
    multi-worker or behind-a-proxy deployment would need shared storage
    and X-Forwarded-For handling — out of scope until that's real.
    """

    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        message: str = "Too many login attempts. Try again later.",
    ) -> None:
        self._message = message
        self._max_attempts = max_attempts
        self._window = timedelta(seconds=window_seconds)
        self._attempts: dict[str, list[datetime]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Counts an attempt for `key`; False once over the limit."""
        now = datetime.now(UTC)
        with self._lock:
            recent = [t for t in self._attempts[key] if now - t < self._window]
            if len(recent) >= self._max_attempts:
                self._attempts[key] = recent
                return False
            recent.append(now)
            self._attempts[key] = recent
            return True

    def check(self, key: str) -> None:
        if not self.allow(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=self._message,
            )

    def reset(self) -> None:
        """Test-only hook — this is process-global state, so tests must
        clear it between runs (see conftest.py's autouse fixture)."""
        with self._lock:
            self._attempts.clear()


login_rate_limiter = LoginRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)

# Changing or resetting a password: same budget, a separate count, keyed
# per account for a change and per address for a reset link.
password_rate_limiter = LoginRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
    message="Too many password attempts. Try again later.",
)

# "Forgot password" emails per address: a few an hour, so nobody can
# flood someone's inbox. Over the limit, requests quietly send nothing.
reset_email_limiter = LoginRateLimiter(max_attempts=3, window_seconds=3600)


def issue_tokens(response: Response, user: User) -> str:
    """Sets a fresh session cookie for `user` and returns a bearer token,
    both under the account's current token_version."""
    set_session_cookie(
        response,
        create_session_token(user_id=user.id, role=user.role, token_version=user.token_version),
    )
    return create_access_token(user_id=user.id, role=user.role, token_version=user.token_version)


def get_current_user(
    response: Response,
    bearer_token: str | None = Depends(oauth2_scheme),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    """Authenticates via the Authorization header (API/script/Swagger
    use) or the session cookie (browser use), header taking priority
    when both are present. A cookie-authenticated request renews the
    cookie's Max-Age — see set_session_cookie's docstring-equivalent
    comment above and ADR-level reasoning in the Phase 3 plan: this is
    what makes an active browser session survive indefinitely while an
    inactive one expires on its own."""
    # Header takes priority when both are present — but "renew the
    # cookie" must only happen when the cookie is actually what
    # authenticated this request, not whenever one happens to also be
    # present alongside an unrelated bearer header (e.g. a test client
    # that carries a stale cookie from an earlier login() call).
    authenticated_via_cookie = bearer_token is None and session_cookie is not None
    token = bearer_token or session_cookie
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode_token(token)
    # A token issued before this claim existed has no "jti" — skip the
    # check rather than treating a missing claim as automatically
    # revoked, so already-issued sessions don't break on deploy.
    jti = payload.get("jti")
    if jti is not None and db.get(RevokedToken, jti) is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked"
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive user"
        )
    # Tokens from before this claim existed count as version 0.
    if payload.get("tv", 0) != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your password was changed. Sign in again.",
        )
    if authenticated_via_cookie:
        set_session_cookie(response, token)
    return user


def require_role(*allowed_roles: Role) -> Callable[[User], User]:
    """Dependency factory: 403s unless the current user's role is in
    allowed_roles. Each router applies this per-endpoint against the
    exact access list spec section 17 defines for that role, rather
    than a single blanket check — different endpoints need different
    role sets.
    """

    def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{current_user.role.value}' is not permitted to perform "
                    f"this action (requires one of: {[r.value for r in allowed_roles]})"
                ),
            )
        return current_user

    return _check
