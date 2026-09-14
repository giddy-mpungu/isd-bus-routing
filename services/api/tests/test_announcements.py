"""spec sections 9/18: dispatcher-authored notices for drivers and/or
families. Always human-authored in this system -- see
routers/announcements.py's module docstring for why."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def test_create_announcement_round_trips_and_defaults_to_general(client, admin_headers):
    response = client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "Buses running 15 minutes late today.", "audience": "family"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["category"] == "general"
    assert body["audience"] == "family"
    assert body["message"] == "Buses running 15 minutes late today."


def test_create_announcement_is_audited(client, admin_headers, db_session):
    response = client.post(
        "/announcements",
        headers=admin_headers,
        json={
            "message": "Route 12 substitute driver today.",
            "category": "substitution",
            "audience": "family",
        },
    )
    announcement_id = response.json()["id"]
    entries = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "announcement", AuditLogEntry.entity_id == announcement_id
        )
        .all()
    )
    assert len(entries) == 1
    assert entries[0].action == "created"
    assert entries[0].after_state["category"] == "substitution"


def test_create_announcement_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER)
    token = login(client, email="driver1@example.org")
    response = client.post(
        "/announcements",
        headers=auth_headers(token),
        json={"message": "Not allowed", "audience": "driver"},
    )
    assert response.status_code == 403


def test_list_announcements_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    make_user(db_session, email="driver2@example.org", role=Role.DRIVER)
    token = login(client, email="driver2@example.org")
    response = client.get("/announcements", headers=auth_headers(token))
    assert response.status_code == 403


def test_list_announcements_returns_newest_first(client, admin_headers):
    client.post(
        "/announcements", headers=admin_headers, json={"message": "First", "audience": "all"}
    )
    client.post(
        "/announcements", headers=admin_headers, json={"message": "Second", "audience": "all"}
    )
    response = client.get("/announcements", headers=admin_headers)
    assert response.status_code == 200, response.text
    messages = [a["message"] for a in response.json()]
    assert messages == ["Second", "First"]


def test_driver_sees_all_and_driver_audience_but_not_family_only(client, admin_headers, db_session):
    client.post(
        "/announcements", headers=admin_headers, json={"message": "For everyone", "audience": "all"}
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For drivers", "audience": "driver"},
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For families", "audience": "family"},
    )

    make_user(db_session, email="driver3@example.org", role=Role.DRIVER)
    token = login(client, email="driver3@example.org")
    response = client.get("/announcements/mine", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    messages = {a["message"] for a in response.json()}
    assert messages == {"For everyone", "For drivers"}


def test_parent_sees_all_and_family_audience_but_not_driver_only(client, admin_headers, db_session):
    client.post(
        "/announcements", headers=admin_headers, json={"message": "For everyone", "audience": "all"}
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For drivers", "audience": "driver"},
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For families", "audience": "family"},
    )

    make_user(db_session, email="parent1@example.org", role=Role.PARENT)
    token = login(client, email="parent1@example.org")
    response = client.get("/announcements/mine", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    messages = {a["message"] for a in response.json()}
    assert messages == {"For everyone", "For families"}


def test_student_sees_family_audience_announcements(client, admin_headers, db_session):
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For families", "audience": "family"},
    )
    make_user(db_session, email="student1@example.org", role=Role.STUDENT)
    token = login(client, email="student1@example.org")
    response = client.get("/announcements/mine", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1


def test_dispatcher_cannot_call_mine_endpoint(client, admin_headers, db_session):
    make_user(db_session, email="dispatcher1@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatcher1@example.org")
    response = client.get("/announcements/mine", headers=auth_headers(token))
    assert response.status_code == 403
