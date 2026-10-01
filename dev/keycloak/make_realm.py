"""Writes a local Keycloak realm for trying single sign-on (Phase 5.4).

Development and testing only. Every run makes a fresh client secret and
fresh user passwords, written to dev/keycloak/out/ (gitignored), so no
credential is ever committed:

  out/isd-dev-realm.json  imported by Keycloak at start-up
  out/api-sso.env         the ISD_API_OIDC_* settings for the api
  out/users.txt           who can sign in, with their passwords

Usage: python dev/keycloak/make_realm.py [api base URL, default http://localhost:8000]
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

OUT = Path(__file__).with_name("out")
REALM = "isd-dev"
CLIENT_ID = "isd-bus-routing"
# Fictional people: the first two match the demo district's accounts
# (src/isd_api/demo_seed.py); the third has no account, to see that message.
USERS = [
    ("dispatcher", "dispatcher@demo.example.org", "Dana", "Dispatcher"),
    ("driver.jordan", "driver.jordan@demo.example.org", "Jordan", "Driver"),
    ("not.in.app", "not.in.app@demo.example.org", "Nobody", "Here"),
]


def main() -> int:
    api = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
    secret = secrets.token_urlsafe(24)
    passwords = {email: secrets.token_urlsafe(12) for _, email, _, _ in USERS}
    realm = {
        "realm": REALM,
        "displayName": "Dev district (local testing only)",
        "enabled": True,
        "sslRequired": "none",
        "clients": [
            {
                "clientId": CLIENT_ID,
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "secret": secret,
                "standardFlowEnabled": True,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "redirectUris": [f"{api}/auth/oidc/callback"],
                "webOrigins": [],
                "attributes": {"pkce.code.challenge.method": "S256"},
            }
        ],
        "users": [
            {
                "username": username,
                "email": email,
                "emailVerified": True,
                "firstName": first,
                "lastName": last,
                "enabled": True,
                "credentials": [{"type": "password", "value": passwords[email], "temporary": False}],
            }
            for username, email, first, last in USERS
        ],
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "isd-dev-realm.json").write_text(json.dumps(realm, indent=2) + "\n", encoding="utf-8")
    (OUT / "api-sso.env").write_text(
        "\n".join(
            [
                f"ISD_API_OIDC_ISSUER=http://localhost:8180/realms/{REALM}",
                f"ISD_API_OIDC_CLIENT_ID={CLIENT_ID}",
                f"ISD_API_OIDC_CLIENT_SECRET={secret}",
                f"ISD_API_OIDC_REDIRECT_URI={api}/auth/oidc/callback",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (OUT / "users.txt").write_text(
        "".join(f"{email}  {passwords[email]}\n" for _, email, _, _ in USERS), encoding="utf-8"
    )
    print(f"Wrote {OUT}: realm, api settings and users (passwords in users.txt).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
