"""Phase 6, spec section 8: district-specific geographic knowledge
overrides. Transportation personnel record local roadway knowledge
commercial mapping data doesn't have; this is POST/GET only in this
slice — wiring it into actual route calculations is deferred, per
spec section 8's own text ("future route calculations")."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user

_PAYLOAD = {
    "location_lat": 29.70,
    "location_lon": -95.40,
    "category": "frequent_flooding",
    "note": "Elm St floods after heavy rain, avoid before 9am on rainy mornings.",
}


def test_admin_can_create_and_list_an_override(client, admin_headers, db_session):
    response = client.post("/geographic-knowledge", headers=admin_headers, json=_PAYLOAD)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["category"] == "frequent_flooding"
    assert body["note"] == _PAYLOAD["note"]
    assert body["location_lat"] == 29.70
    assert "created_at" in body

    listed = client.get("/geographic-knowledge", headers=admin_headers)
    assert listed.status_code == 200
    assert [o["id"] for o in listed.json()] == [body["id"]]

    entries = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "geographic_knowledge_override",
            AuditLogEntry.action == "created",
        )
        .all()
    )
    assert len(entries) == 1
    assert entries[0].actor_user_id is not None


def test_dispatcher_can_also_create_and_list(client, db_session):
    make_user(db_session, email="dispatcher@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatcher@example.org")
    headers = auth_headers(token)

    response = client.post("/geographic-knowledge", headers=headers, json=_PAYLOAD)
    assert response.status_code == 201, response.text

    listed = client.get("/geographic-knowledge", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_other_roles_are_rejected(client, db_session):
    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    headers = auth_headers(token)

    create_response = client.post("/geographic-knowledge", headers=headers, json=_PAYLOAD)
    assert create_response.status_code == 403

    list_response = client.get("/geographic-knowledge", headers=headers)
    assert list_response.status_code == 403


def test_multiple_overrides_are_listed_in_id_order(client, admin_headers):
    first = client.post("/geographic-knowledge", headers=admin_headers, json=_PAYLOAD)
    second_payload = {
        **_PAYLOAD,
        "category": "unsafe_turn",
        "note": "Left turn onto Main is legal but blind.",
    }
    second = client.post("/geographic-knowledge", headers=admin_headers, json=second_payload)
    assert first.status_code == 201 and second.status_code == 201

    listed = client.get("/geographic-knowledge", headers=admin_headers).json()
    assert [o["id"] for o in listed] == [first.json()["id"], second.json()["id"]]
    assert listed[1]["category"] == "unsafe_turn"


def test_rejects_empty_note(client, admin_headers):
    response = client.post(
        "/geographic-knowledge", headers=admin_headers, json={**_PAYLOAD, "note": ""}
    )
    assert response.status_code == 422


def test_rejects_out_of_range_latitude(client, admin_headers):
    response = client.post(
        "/geographic-knowledge", headers=admin_headers, json={**_PAYLOAD, "location_lat": 95.0}
    )
    assert response.status_code == 422


def test_rejects_invalid_category(client, admin_headers):
    response = client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={**_PAYLOAD, "category": "not_a_real_category"},
    )
    assert response.status_code == 422
