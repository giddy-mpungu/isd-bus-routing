"""Edit/deactivate for core master data (spec section 3.1 "relocate ...
stops", spec section 21 "reassign buses"/"reassign drivers"): PATCH on
Vehicle, Driver, Qualification, and PATCH/DELETE on Stop. Before this,
these entities were create-and-list only -- a typo or a retired
vehicle/driver had no way to be corrected or hidden through the API."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def _vehicle(client, admin_headers, **overrides):
    payload = {"label": "Bus 1", "nominal_capacity": 48}
    payload.update(overrides)
    return client.post("/vehicles", headers=admin_headers, json=payload).json()


def _driver(client, admin_headers, **overrides):
    payload = {"full_name": "Driver A"}
    payload.update(overrides)
    return client.post("/drivers", headers=admin_headers, json=payload).json()


def _qualification(client, admin_headers, code="wheelchair", **overrides):
    payload = {"code": code, "kind": "vehicle_capability", "description": "Wheelchair lift"}
    payload.update(overrides)
    return client.post("/qualifications", headers=admin_headers, json=payload).json()


def _stop(client, admin_headers, **overrides):
    payload = {"label": "Main St & 1st", "location_lat": 29.7, "location_lon": -95.4}
    payload.update(overrides)
    return client.post("/stops", headers=admin_headers, json=payload).json()


# --- Vehicle ---


def test_update_vehicle_edits_fields_and_audits(client, admin_headers, db_session):
    vehicle = _vehicle(client, admin_headers, label="Bus 1", nominal_capacity=48)
    response = client.patch(
        f"/vehicles/{vehicle['id']}",
        headers=admin_headers,
        json={"label": "Bus 101", "effective_capacity": 44, "length_m": 12.5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == "Bus 101"
    assert body["effective_capacity"] == 44
    assert body["length_m"] == 12.5
    assert body["nominal_capacity"] == 48  # untouched field survives

    entry = db_session.query(AuditLogEntry).filter_by(entity_type="vehicle").one()
    assert entry.before_state["label"] == "Bus 1"
    assert entry.after_state["label"] == "Bus 101"


def test_update_vehicle_can_change_qualifications(client, admin_headers):
    _qualification(client, admin_headers, code="wheelchair")
    _qualification(client, admin_headers, code="lift")
    vehicle = _vehicle(client, admin_headers, qualification_codes=["wheelchair"])
    response = client.patch(
        f"/vehicles/{vehicle['id']}", headers=admin_headers, json={"qualification_codes": ["lift"]}
    )
    assert [q["code"] for q in response.json()["qualifications"]] == ["lift"]


def test_update_vehicle_rejects_unknown_qualification_code(client, admin_headers):
    vehicle = _vehicle(client, admin_headers)
    response = client.patch(
        f"/vehicles/{vehicle['id']}", headers=admin_headers, json={"qualification_codes": ["ghost"]}
    )
    assert response.status_code == 400


def test_vehicle_can_be_deactivated_and_reactivated(client, admin_headers):
    vehicle = _vehicle(client, admin_headers)
    deactivated = client.patch(
        f"/vehicles/{vehicle['id']}", headers=admin_headers, json={"is_active": False}
    )
    assert deactivated.json()["is_active"] is False
    listed = client.get("/vehicles", headers=admin_headers).json()
    assert next(v for v in listed if v["id"] == vehicle["id"])["is_active"] is False

    reactivated = client.patch(
        f"/vehicles/{vehicle['id']}", headers=admin_headers, json={"is_active": True}
    )
    assert reactivated.json()["is_active"] is True


def test_deactivating_a_vehicle_does_not_touch_its_existing_crew(client, admin_headers):
    vehicle = _vehicle(client, admin_headers)
    driver = _driver(client, admin_headers)
    crew = client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    ).json()

    client.patch(f"/vehicles/{vehicle['id']}", headers=admin_headers, json={"is_active": False})

    crews = client.get(
        "/crews", headers=admin_headers, params={"service_date": "2026-09-01"}
    ).json()
    assert next(c for c in crews if c["id"] == crew["id"])["vehicle_id"] == vehicle["id"]


def test_update_vehicle_validation_and_not_found(client, admin_headers):
    vehicle = _vehicle(client, admin_headers)
    bad = client.patch(
        f"/vehicles/{vehicle['id']}", headers=admin_headers, json={"nominal_capacity": -1}
    )
    assert bad.status_code == 422
    missing = client.patch("/vehicles/999999", headers=admin_headers, json={"label": "x"})
    assert missing.status_code == 404


def test_only_transportation_admin_can_update_a_vehicle(client, admin_headers, db_session):
    vehicle = _vehicle(client, admin_headers)
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    headers = auth_headers(login(client, email="disp@example.org"))
    response = client.patch(
        f"/vehicles/{vehicle['id']}", headers=headers, json={"label": "Hijacked"}
    )
    assert response.status_code == 403


# --- Driver ---


def test_update_driver_edits_fields_qualifications_and_active_flag(
    client, admin_headers, db_session
):
    _qualification(client, admin_headers, code="CDL_B", kind="license")
    driver = _driver(client, admin_headers, full_name="Jordan Old")
    response = client.patch(
        f"/drivers/{driver['id']}",
        headers=admin_headers,
        json={
            "full_name": "Jordan New",
            "max_continuous_minutes": 480,
            "qualification_codes": ["CDL_B"],
            "is_active": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == "Jordan New"
    assert body["max_continuous_minutes"] == 480
    assert [q["code"] for q in body["qualifications"]] == ["CDL_B"]
    assert body["is_active"] is False

    entry = db_session.query(AuditLogEntry).filter_by(entity_type="driver").one()
    assert entry.after_state["is_active"] is False


def test_update_driver_not_found_and_forbidden(client, admin_headers, db_session):
    assert (
        client.patch("/drivers/999999", headers=admin_headers, json={"full_name": "x"}).status_code
        == 404
    )
    driver = _driver(client, admin_headers)
    make_user(db_session, email="drv@example.org", role=Role.DRIVER)
    headers = auth_headers(login(client, email="drv@example.org"))
    assert (
        client.patch(
            f"/drivers/{driver['id']}", headers=headers, json={"full_name": "x"}
        ).status_code
        == 403
    )


# --- Qualification ---


def test_update_qualification_description_and_active_flag(client, admin_headers, db_session):
    qualification = _qualification(client, admin_headers, description="Old description")
    response = client.patch(
        f"/qualifications/{qualification['id']}",
        headers=admin_headers,
        json={"description": "New description", "is_active": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["description"] == "New description"
    assert response.json()["is_active"] is False
    # code/kind are immutable via this endpoint.
    assert response.json()["code"] == qualification["code"]

    entry = db_session.query(AuditLogEntry).filter_by(entity_type="qualification").one()
    assert entry.before_state["description"] == "Old description"


def test_update_qualification_ignores_code_and_kind_fields_if_sent(client, admin_headers):
    qualification = _qualification(
        client, admin_headers, code="wheelchair", kind="vehicle_capability"
    )
    response = client.patch(
        f"/qualifications/{qualification['id']}",
        headers=admin_headers,
        json={"code": "hijacked", "kind": "license"},
    )
    # Extra/unknown fields on a Pydantic model are ignored by default,
    # not rejected -- confirm the update still applies harmlessly and
    # code/kind genuinely didn't change.
    assert response.status_code == 200, response.text
    assert response.json()["code"] == "wheelchair"
    assert response.json()["kind"] == "vehicle_capability"


def test_update_qualification_not_found(client, admin_headers):
    response = client.patch(
        "/qualifications/999999", headers=admin_headers, json={"description": "x"}
    )
    assert response.status_code == 404


# --- Stop ---


def test_update_stop_relocates_it_and_audits(client, admin_headers, db_session):
    stop = _stop(client, admin_headers, label="Old label", location_lat=1.0, location_lon=1.0)
    response = client.patch(
        f"/stops/{stop['id']}",
        headers=admin_headers,
        json={"label": "New label", "location_lat": 2.0, "location_lon": 2.0},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == "New label"
    assert (body["location_lat"], body["location_lon"]) == (2.0, 2.0)

    entry = db_session.query(AuditLogEntry).filter_by(entity_type="stop", action="updated").one()
    assert entry.before_state["label"] == "Old label"


def test_update_stop_not_found(client, admin_headers):
    response = client.patch("/stops/999999", headers=admin_headers, json={"label": "x"})
    assert response.status_code == 404


def test_delete_unused_stop_succeeds_and_audits(client, admin_headers, db_session):
    stop = _stop(client, admin_headers)
    response = client.delete(f"/stops/{stop['id']}", headers=admin_headers)
    assert response.status_code == 204
    assert client.get("/stops", headers=admin_headers).json() == []
    entry = db_session.query(AuditLogEntry).filter_by(entity_type="stop", action="deleted").one()
    assert entry.before_state["label"] == stop["label"]


def test_delete_stop_in_use_is_rejected_with_409(client, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Riverside Elementary", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    stop = _stop(client, admin_headers)
    client.post(
        "/students",
        headers=admin_headers,
        json={"full_name": "Ana Lopez", "school_id": school["id"], "stop_id": stop["id"]},
    )
    response = client.delete(f"/stops/{stop['id']}", headers=admin_headers)
    assert response.status_code == 409
    assert client.get("/stops", headers=admin_headers).json() != []


def test_delete_stop_not_found(client, admin_headers):
    assert client.delete("/stops/999999", headers=admin_headers).status_code == 404


def test_only_transportation_admin_can_edit_or_delete_a_stop(client, admin_headers, db_session):
    stop = _stop(client, admin_headers)
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    headers = auth_headers(login(client, email="disp@example.org"))
    assert (
        client.patch(f"/stops/{stop['id']}", headers=headers, json={"label": "x"}).status_code
        == 403
    )
    assert client.delete(f"/stops/{stop['id']}", headers=headers).status_code == 403
