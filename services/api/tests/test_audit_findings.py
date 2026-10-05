"""Findings from the 2026-10-04 audit of the running demo."""

import pytest

from isd_api.config import Settings
from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user


@pytest.mark.parametrize(
    ("environment", "override", "expected"),
    [
        ("dev", None, True),
        ("test", None, True),
        ("production", None, False),
        ("production", True, True),
        ("dev", False, False),
    ],
)
def test_api_docs_are_hidden_in_production_unless_asked_for(environment, override, expected):
    settings = Settings(environment=environment, expose_api_docs=override)
    assert settings.api_docs_enabled is expected


def test_api_docs_are_served_outside_production(client):
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("role", [Role.DRIVER, Role.PARENT, Role.STUDENT, Role.SCHOOL_ADMIN])
def test_only_staff_list_qualifications(client, db_session, admin_headers, role):
    assert client.get("/qualifications", headers=admin_headers).status_code == 200
    make_user(db_session, email="someone@example.org", role=role)
    headers = auth_headers(login(client, email="someone@example.org"))
    assert client.get("/qualifications", headers=headers).status_code == 403


def test_dispatchers_still_list_qualifications(client, db_session):
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    headers = auth_headers(login(client, email="disp@example.org"))
    assert client.get("/qualifications", headers=headers).status_code == 200
