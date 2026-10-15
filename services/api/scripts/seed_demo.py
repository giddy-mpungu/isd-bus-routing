"""Load the fictional demo district into an EMPTY install (see
isd_api/demo_seed.py and docs/demo.md). Runs inside the api container,
against the api server already running there:

    docker compose ... exec api python scripts/seed_demo.py

Every password is generated here, never passed in on a command line.
The created logins are printed to stdout as JSON (and nothing else goes
to stdout) so scripts/demo.ps1 can save them to a gitignored file;
progress messages go to stderr.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from isd_api.db import SessionLocal
from isd_api.demo_seed import (
    ADMIN_EMAIL,
    AlreadySeededError,
    create_demo_admin,
    generate_password,
    seed_demo,
)
from isd_api.models import User
from isd_api.security import create_access_token

API = os.environ.get("ISD_DEMO_SEED_API", "http://localhost:8000")


def _call(method: str, path: str, body: Any, headers: dict[str, str]) -> Any:
    data = None
    if isinstance(body, bytes):
        data = body
    elif body is not None:
        data = json.dumps(body).encode()
        headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read()
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"{method} {path} -> {err.code}: {err.read().decode()}") from err
    return json.loads(raw) if raw else None


def main() -> int:
    admin_password = generate_password()
    db = SessionLocal()
    try:
        admin = create_demo_admin(db, admin_password)
        user = db.query(User).filter(User.email == ADMIN_EMAIL).one()
        # The admin's role needs two-step sign-in, so a password login
        # gives no token until an authenticator is set up (isd_api/mfa.py).
        # This script runs on the server with database access, the same
        # trust as scripts/bootstrap_admin.py, so it issues its own
        # short-lived token instead. The admin still sets up two-step
        # sign-in at their first browser sign-in.
        token = create_access_token(
            user_id=user.id,
            role=user.role,
            token_version=user.token_version,
            mfa=True,
            expires_delta=timedelta(minutes=30),
        )
    except AlreadySeededError as err:
        print(f"Skipping demo seed: {err}", file=sys.stderr)
        return 3
    finally:
        db.close()

    auth = {"Authorization": f"Bearer {token}"}

    # UTC "today", matching what the web app itself treats as today
    # (it derives the date from toISOString()).
    today = datetime.now(UTC).date()
    print(f"Seeding the demo district from {today}...", file=sys.stderr)
    accounts = seed_demo(
        lambda method, path, body: _call(method, path, body, auth), start_date=today
    )
    print(json.dumps([asdict(a) for a in [admin, *accounts]]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
