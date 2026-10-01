"""Two-step sign-in with an authenticator app (Phase 5.3).

Decisions by the product owner (2026-09-30): time-based one-time codes
(TOTP, RFC 6238, what Google/Microsoft Authenticator and password
managers speak), required for the roles in `ISD_API_MFA_REQUIRED_ROLES`
(transportation admins and dispatchers), optional for school admins and
families, not used on driver accounts (shared tablets). Staff without it
set it up at their next sign-in; there's no "remember this device"; a
transportation admin can reset someone else's.

Each person's secret is encrypted in the database with
`ISD_API_MFA_ENCRYPTION_KEY` (Fernet), so a copy of the database can't
produce codes. A code is accepted once: the time step it came from is
remembered and older or equal steps are refused. Ten single-use recovery
codes are stored as SHA-256 hashes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import UTC, datetime
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from isd_api.config import settings
from isd_api.models import MfaRecoveryCode, Role, User

PERIOD_SECONDS = 30
DIGITS = 6
# Codes from the step before or after the current one still count, for
# clock drift and for someone typing as the code rolls over.
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def is_allowed(user: User) -> bool:
    return user.role != Role.DRIVER


def is_required(user: User) -> bool:
    return user.mfa_required


def is_enabled(user: User) -> bool:
    return user.mfa_secret_encrypted is not None


def _fernet() -> Fernet:
    return Fernet(settings.mfa_fernet_key)


def encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("ascii")
    except InvalidToken as exc:
        raise RuntimeError(
            "Can't read a stored authenticator secret: ISD_API_MFA_ENCRYPTION_KEY changed"
        ) from exc


def new_secret() -> str:
    """160 random bits, base32 without padding, as authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def code_at(secret: str, step: int) -> str:
    """The RFC 6238 code for one 30-second step (HMAC-SHA1, 6 digits)."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD_SECONDS)


def matching_step(
    secret: str, code: str, after: int | None, now: float | None = None
) -> int | None:
    """The step `code` belongs to, if it's valid now and newer than `after`."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if after is not None and candidate <= after:
            continue
        if hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def otpauth_uri(secret: str, email: str) -> str:
    issuer = settings.mfa_issuer
    label = quote(f"{issuer}:{email}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD_SECONDS}"
    )


def verify_code(user: User, code: str) -> bool:
    """Checks a code against the user's authenticator and remembers its
    step, so the same code can't be used twice. The caller commits."""
    if user.mfa_secret_encrypted is None:
        return False
    step = matching_step(decrypt(user.mfa_secret_encrypted), code, user.mfa_last_step)
    if step is None:
        return False
    user.mfa_last_step = step
    return True


def _normalise_recovery(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _hash_recovery(code: str) -> str:
    return hashlib.sha256(_normalise_recovery(code).encode("ascii")).hexdigest()


def new_recovery_codes(db: Session, user: User) -> list[str]:
    """Replaces the user's recovery codes; returns them (shown once)."""
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id).delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
        db.add(MfaRecoveryCode(user_id=user.id, code_hash=_hash_recovery(raw)))
    return codes


def use_recovery_code(db: Session, user: User, code: str) -> bool:
    if len(_normalise_recovery(code)) != 10:
        return False
    row = (
        db.query(MfaRecoveryCode)
        .filter(
            MfaRecoveryCode.user_id == user.id,
            MfaRecoveryCode.code_hash == _hash_recovery(code),
            MfaRecoveryCode.used_at.is_(None),
        )
        .one_or_none()
    )
    if row is None:
        return False
    row.used_at = datetime.now(UTC)
    return True


def recovery_codes_left(db: Session, user: User) -> int:
    return (
        db.query(MfaRecoveryCode)
        .filter(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None))
        .count()
    )


def turn_off(db: Session, user: User) -> None:
    user.mfa_secret_encrypted = None
    user.mfa_pending_secret_encrypted = None
    user.mfa_last_step = None
    user.mfa_enabled_at = None
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id).delete()
