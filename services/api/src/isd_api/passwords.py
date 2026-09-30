"""Password rules and one-time reset links (Phase 5.1).

The minimum length is a deployment setting (`ISD_API_PASSWORD_MIN_LENGTH`,
8 by default, the product owner's choice of 2026-09-30). On top of it,
the passwords attackers try first are refused, and so is the account's
own email. Existing passwords keep working until they are next changed.

A reset link carries a random token that is stored only as a SHA-256
hash, so a copy of the database can't be used to reset anyone. It works
once, for `ISD_API_PASSWORD_RESET_LINK_HOURS` (24 by default), and
issuing a new one cancels any the account already had.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from isd_api.config import settings
from isd_api.models import PasswordResetToken, User

# bcrypt only reads the first 72 bytes; anything longer would be
# silently cut, so it's refused instead.
MAX_BYTES = 72

# The most-used passwords from public breach lists, all 8+ characters
# (shorter ones already fail the length rule). Compared ignoring case.
COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password12",
        "password123",
        "password1234",
        "passw0rd",
        "p@ssw0rd",
        "p@ssword",
        "12345678",
        "123456789",
        "1234567890",
        "12341234",
        "11111111",
        "00000000",
        "87654321",
        "123123123",
        "qwertyuiop",
        "qwerty123",
        "qwerty12",
        "1q2w3e4r",
        "1q2w3e4r5t",
        "1qaz2wsx",
        "zaq12wsx",
        "asdfghjkl",
        "asdf1234",
        "iloveyou",
        "iloveyou1",
        "princess",
        "sunshine",
        "football",
        "baseball",
        "basketball",
        "superman",
        "starwars",
        "welcome1",
        "welcome123",
        "letmein1",
        "trustno1",
        "whatever",
        "computer",
        "internet",
        "michelle",
        "jennifer",
        "abcd1234",
        "abc12345",
        "aa123456",
        "changeme",
        "changeme1",
        "admin123",
        "administrator",
        "school123",
        "teacher1",
        "student1",
        "schoolbus",
        "busdriver",
        "transportation",
    }
)


def policy_problem(password: str, email: str) -> str | None:
    """Why `password` can't be used for the account `email`, or None."""
    if len(password) < settings.password_min_length:
        return f"Use at least {settings.password_min_length} characters"
    if len(password.encode("utf-8")) > MAX_BYTES:
        return "That password is too long"
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        return "That password is too common; choose another"
    email = email.lower()
    if lowered == email or lowered == email.split("@", 1)[0]:
        return "Don't use your email as your password"
    return None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_reset_token(
    db: Session, user: User, issued_by: User | None, lifetime: timedelta | None = None
) -> tuple[PasswordResetToken, str]:
    """A new single-use token for `user`: the row and the plain token,
    which is never stored. Earlier unused ones are removed. The caller
    commits."""
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
    ).delete()
    plain = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_token(plain),
        created_at=now,
        expires_at=now + (lifetime or timedelta(hours=settings.password_reset_link_hours)),
        created_by_user_id=issued_by.id if issued_by else None,
    )
    db.add(row)
    db.flush()
    return row, plain


def redeem_reset_token(db: Session, plain: str) -> PasswordResetToken | None:
    """The unused, unexpired token matching `plain`, if any."""
    return (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == _hash_token(plain),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(UTC),
        )
        .one_or_none()
    )
