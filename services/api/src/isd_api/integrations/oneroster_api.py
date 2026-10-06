"""OneRoster 1.1 REST client for the scheduled SIS sync (isd_api/sis_sync.py).

Chosen by the product owner on 2026-10-06 as the scheduled source: the
standard API most SIS platforms offer (PowerSchool, Infinite Campus,
Skyward, or a hub such as ClassLink). Authentication is OAuth 2 client
credentials, which current OneRoster providers support; the token comes
from `ISD_API_SIS_ONEROSTER_TOKEN_URL` and is used only for this pull.

Reads `GET {base}/students` page by page (`limit`/`offset`), as the
standard defines, and hands the `users` objects to the same row rules as
the CSV import (integrations/oneroster.py `parse_students_api`). Only the
standard library: no new dependency. Errors carry no secrets.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from isd_api.config import settings
from isd_api.integrations.oneroster import MAX_ROWS

PAGE_SIZE = 1000
TIMEOUT_SECONDS = 30


class OneRosterApiError(RuntimeError):
    """The roster couldn't be fetched; the message is safe to show."""


def is_configured() -> bool:
    return bool(
        settings.sis_oneroster_base_url
        and settings.sis_oneroster_token_url
        and settings.sis_oneroster_client_id
        and settings.sis_oneroster_client_secret
    )


def http_json(
    url: str, *, headers: dict[str, str], form: dict[str, str] | None = None
) -> dict[str, Any]:
    """GET (or POST a form to) `url` and parse the JSON reply."""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Accept": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise OneRosterApiError(f"The SIS answered {exc.code} for {_where(url)}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OneRosterApiError(f"The SIS couldn't be reached at {_where(url)}") from exc
    except ValueError as exc:
        raise OneRosterApiError(
            f"The SIS sent something that isn't JSON from {_where(url)}"
        ) from exc
    if not isinstance(body, dict):
        raise OneRosterApiError(f"Unexpected reply from {_where(url)}")
    return body


def _where(url: str) -> str:
    """The address without its query string (no tokens or ids in messages)."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _token() -> str:
    credentials = f"{settings.sis_oneroster_client_id}:{settings.sis_oneroster_client_secret}"
    form = {"grant_type": "client_credentials"}
    if settings.sis_oneroster_scope:
        form["scope"] = settings.sis_oneroster_scope
    reply = http_json(
        settings.sis_oneroster_token_url or "",
        headers={"Authorization": "Basic " + base64.b64encode(credentials.encode()).decode()},
        form=form,
    )
    token = reply.get("access_token")
    if not isinstance(token, str) or not token:
        raise OneRosterApiError(
            "The SIS sign-in gave no access token; check the client ID and secret"
        )
    return token


def fetch_students() -> list[dict[str, Any]]:
    """Every student user the SIS lists, across all pages."""
    if not is_configured():
        raise OneRosterApiError("The SIS connection isn't set up (ISD_API_SIS_ONEROSTER_*)")
    headers = {"Authorization": f"Bearer {_token()}"}
    base = (settings.sis_oneroster_base_url or "").rstrip("/")
    users: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = http_json(f"{base}/students?limit={PAGE_SIZE}&offset={offset}", headers=headers)
        batch = page.get("users")
        if not isinstance(batch, list):
            raise OneRosterApiError("The SIS's students list wasn't in the OneRoster format")
        users.extend(u for u in batch if isinstance(u, dict))
        if len(users) > MAX_ROWS:
            raise OneRosterApiError(f"The SIS listed more than {MAX_ROWS} students")
        if len(batch) < PAGE_SIZE:
            return users
        offset += PAGE_SIZE
