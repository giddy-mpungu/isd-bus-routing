"""Create the first Transportation Administrator user.

There's a chicken-and-egg problem with RBAC: POST /users requires an
existing transportation_admin. This script is the one place that's
allowed to create a user without that check — and it refuses to run if
any user already exists, so it can't be used to silently mint a second
admin later. Credentials are read from environment variables, never
hardcoded or passed as CLI arguments (which would land in shell history).

Usage:
    ISD_API_BOOTSTRAP_EMAIL=admin@example.org \
    ISD_API_BOOTSTRAP_PASSWORD='...' \
    ISD_API_BOOTSTRAP_NAME='Jane Admin' \
    python scripts/bootstrap_admin.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy.exc import OperationalError

from isd_api.db import SessionLocal
from isd_api.models import Role, User
from isd_api.security import hash_password


def main() -> int:
    email = os.environ.get("ISD_API_BOOTSTRAP_EMAIL")
    password = os.environ.get("ISD_API_BOOTSTRAP_PASSWORD")
    full_name = os.environ.get("ISD_API_BOOTSTRAP_NAME")

    if not email or not password or not full_name:
        print(
            "ISD_API_BOOTSTRAP_EMAIL, ISD_API_BOOTSTRAP_PASSWORD, and "
            "ISD_API_BOOTSTRAP_NAME must all be set in the environment.",
            file=sys.stderr,
        )
        return 1
    if len(password) < 8:
        print("ISD_API_BOOTSTRAP_PASSWORD must be at least 8 characters.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        try:
            user_count = db.query(User).count()
        except OperationalError:
            print(
                "Database schema not found. Run `alembic upgrade head` first, "
                "then re-run this script.",
                file=sys.stderr,
            )
            return 1

        if user_count > 0:
            print(
                "Refusing to bootstrap: users already exist. Create additional "
                "admins via POST /users as an existing transportation_admin.",
                file=sys.stderr,
            )
            return 1

        admin = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=Role.TRANSPORTATION_ADMIN,
        )
        db.add(admin)
        db.commit()
        print(f"Created transportation_admin user: {email}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
