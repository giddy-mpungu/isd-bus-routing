"""spec section 12.3: reusable transportation-specific information for
a frequently used field-trip destination."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def test_create_destination_profile_round_trips(client, admin_headers):
    response = client.post(
        "/destination-profiles",
        headers=admin_headers,
        json={
            "name": "State Science Museum",
            "location_lat": 29.76,
            "location_lon": -95.37,
            "approved_entrance": "North doors, Bus Lane 3",
            "parking_notes": "Overflow lot across the street after 9am",
            "turn_restrictions": "No left turn onto Main St from the bus lane",
            "driver_notes": "Security will wave buses through the gate",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "State Science Museum"
    assert body["approved_entrance"] == "North doors, Bus Lane 3"

    listed = client.get("/destination-profiles", headers=admin_headers).json()
    assert any(p["id"] == body["id"] for p in listed)


def test_create_destination_profile_is_audited(client, admin_headers, db_session):
    response = client.post(
        "/destination-profiles", headers=admin_headers, json={"name": "State Science Museum"}
    )
    profile_id = response.json()["id"]
    entries = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "destination_profile",
            AuditLogEntry.entity_id == profile_id,
        )
        .all()
    )
    assert len(entries) == 1
    assert entries[0].action == "created"


def test_create_destination_profile_requires_admin_or_dispatcher_role(
    client, admin_headers, db_session
):
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER)
    token = login(client, email="driver1@example.org")
    response = client.post(
        "/destination-profiles", headers=auth_headers(token), json={"name": "Not allowed"}
    )
    assert response.status_code == 403


def test_list_destination_profiles_requires_admin_or_dispatcher_role(
    client, admin_headers, db_session
):
    make_user(db_session, email="driver2@example.org", role=Role.DRIVER)
    token = login(client, email="driver2@example.org")
    response = client.get("/destination-profiles", headers=auth_headers(token))
    assert response.status_code == 403
