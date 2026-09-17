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


def test_congestion_window_round_trips_with_its_time_range(client, admin_headers):
    response = client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            "location_lat": 29.70,
            "location_lon": -95.40,
            "category": "congestion_window",
            "note": "Main St backs up during morning drop-off.",
            "window_start_minute": 420,
            "window_end_minute": 480,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["window_start_minute"] == 420
    assert body["window_end_minute"] == 480
    assert body["restricted_dimension"] is None
    assert body["max_allowed_value"] is None


def test_congestion_window_requires_both_window_fields(client, admin_headers):
    response = client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            **_PAYLOAD,
            "category": "congestion_window",
            "window_start_minute": 420,
        },
    )
    assert response.status_code == 400


def test_congestion_window_rejects_start_after_end(client, admin_headers):
    response = client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            **_PAYLOAD,
            "category": "congestion_window",
            "window_start_minute": 480,
            "window_end_minute": 420,
        },
    )
    assert response.status_code == 400


def test_window_fields_are_rejected_for_a_non_congestion_category(client, admin_headers):
    response = client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={**_PAYLOAD, "window_start_minute": 420, "window_end_minute": 480},
    )
    assert response.status_code == 400


def test_vehicle_size_restricted_round_trips_with_its_threshold(client, admin_headers):
    response = client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            "location_lat": 29.70,
            "location_lon": -95.40,
            "category": "vehicle_size_restricted",
            "note": "Covered bridge on Elm St has a 3.0m height limit.",
            "restricted_dimension": "height_m",
            "max_allowed_value": 3.0,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["restricted_dimension"] == "height_m"
    assert body["max_allowed_value"] == 3.0
    assert body["window_start_minute"] is None
    assert body["window_end_minute"] is None


def test_vehicle_size_restricted_requires_both_threshold_fields(client, admin_headers):
    response = client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            **_PAYLOAD,
            "category": "vehicle_size_restricted",
            "restricted_dimension": "height_m",
        },
    )
    assert response.status_code == 400


def test_threshold_fields_are_rejected_for_a_non_size_restricted_category(client, admin_headers):
    response = client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={**_PAYLOAD, "restricted_dimension": "height_m", "max_allowed_value": 3.0},
    )
    assert response.status_code == 400


def test_rejects_non_positive_max_allowed_value(client, admin_headers):
    response = client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            **_PAYLOAD,
            "category": "vehicle_size_restricted",
            "restricted_dimension": "height_m",
            "max_allowed_value": 0,
        },
    )
    assert response.status_code == 422
