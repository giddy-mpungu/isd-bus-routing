"""spec section 17/21: the audit trail made readable. Every mutation
already writes an AuditLogEntry (isd_api.audit.record) -- this is the
first endpoint that reads any of it back. transportation_admin only."""

from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user


def test_transportation_admin_sees_audit_entries_with_resolved_actor_name(client, admin_headers):
    created = client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "Buses running late.", "audience": "family"},
    ).json()

    response = client.get("/audit-log", headers=admin_headers)
    assert response.status_code == 200, response.text
    entries = response.json()
    matching = [
        e for e in entries if e["entity_type"] == "announcement" and e["entity_id"] == created["id"]
    ]
    assert len(matching) == 1
    assert matching[0]["action"] == "created"
    assert matching[0]["actor_full_name"] == "admin"  # admin_headers's own full_name
    assert matching[0]["after_state"]["message"] == "Buses running late."


def test_dispatcher_cannot_access_audit_log(client, admin_headers, db_session):
    make_user(db_session, email="dispatcher@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatcher@example.org")
    response = client.get("/audit-log", headers=auth_headers(token))
    assert response.status_code == 403


def test_other_roles_cannot_access_audit_log(client, admin_headers, db_session):
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER)
    token = login(client, email="driver1@example.org")
    response = client.get("/audit-log", headers=auth_headers(token))
    assert response.status_code == 403


def test_filters_by_entity_type(client, admin_headers):
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "Announcement one.", "audience": "family"},
    )
    client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            "location_lat": 29.7,
            "location_lon": -95.4,
            "category": "frequent_flooding",
            "note": "Floods after heavy rain.",
        },
    )
    response = client.get(
        "/audit-log", headers=admin_headers, params={"entity_type": "geographic_knowledge_override"}
    )
    assert response.status_code == 200, response.text
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["entity_type"] == "geographic_knowledge_override"


def test_filters_by_entity_id(client, admin_headers):
    first = client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "First.", "audience": "family"},
    ).json()
    second = client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "Second.", "audience": "family"},
    ).json()

    response = client.get(
        "/audit-log",
        headers=admin_headers,
        params={"entity_type": "announcement", "entity_id": first["id"]},
    )
    assert response.status_code == 200, response.text
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["entity_id"] == first["id"]
    assert entries[0]["after_state"]["message"] == "First."
    assert second["id"] != first["id"]


def test_newest_first_and_limit(client, admin_headers):
    for i in range(3):
        client.post(
            "/announcements",
            headers=admin_headers,
            json={"message": f"Message {i}.", "audience": "family"},
        )
    response = client.get(
        "/audit-log", headers=admin_headers, params={"entity_type": "announcement", "limit": 2}
    )
    assert response.status_code == 200, response.text
    entries = response.json()
    assert len(entries) == 2
    assert entries[0]["after_state"]["message"] == "Message 2."
    assert entries[1]["after_state"]["message"] == "Message 1."


def test_offset_pages_through_results(client, admin_headers):
    for i in range(3):
        client.post(
            "/announcements",
            headers=admin_headers,
            json={"message": f"Message {i}.", "audience": "family"},
        )
    response = client.get(
        "/audit-log",
        headers=admin_headers,
        params={"entity_type": "announcement", "limit": 2, "offset": 2},
    )
    assert response.status_code == 200, response.text
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["after_state"]["message"] == "Message 0."


def test_rejects_limit_above_the_cap(client, admin_headers):
    response = client.get("/audit-log", headers=admin_headers, params={"limit": 501})
    assert response.status_code == 422


def test_entity_types_lists_only_types_that_actually_occur(client, admin_headers):
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "One.", "audience": "family"},
    )
    response = client.get("/audit-log/entity-types", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert "announcement" in response.json()
    assert "school" not in response.json()  # schools.py doesn't audit its own creation


def test_entity_types_requires_transportation_admin(client, admin_headers, db_session):
    make_user(db_session, email="dispatcher2@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatcher2@example.org")
    response = client.get("/audit-log/entity-types", headers=auth_headers(token))
    assert response.status_code == 403
