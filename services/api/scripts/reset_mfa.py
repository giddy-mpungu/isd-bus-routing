"""Reset one account's two-step sign-in from the server (Phase 5.3).

The last resort when the only transportation admin has lost their phone
and their recovery codes: normally another admin does this from Users.
It turns two-step sign-in off and signs the account out everywhere; the
person sets it up again at their next sign-in. The email is read from an
environment variable, like scripts/bootstrap_admin.py.

Usage:
    ISD_API_RESET_MFA_EMAIL=admin@example.org python scripts/reset_mfa.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import func

from isd_api import mfa
from isd_api.audit import record as record_audit
from isd_api.db import SessionLocal
from isd_api.models import User


def main() -> int:
    email = (os.environ.get("ISD_API_RESET_MFA_EMAIL") or "").strip().lower()
    if not email:
        print("Set ISD_API_RESET_MFA_EMAIL to the account's email.", file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        user = db.query(User).filter(func.lower(User.email) == email).first()
        if user is None:
            print(f"No account with the email {email}.", file=sys.stderr)
            return 1
        mfa.turn_off(db, user)
        user.token_version += 1
        record_audit(db, entity_type="user", entity_id=user.id, action="mfa_reset", actor=None)
        db.commit()
        print(f"Two-step sign-in reset for {user.email}; they'll set it up at next sign-in.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
