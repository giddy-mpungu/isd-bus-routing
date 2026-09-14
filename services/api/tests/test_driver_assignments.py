"""Phase 4 driver-facing endpoints: GET .../my-assignments (denormalized,
scoped to the logged-in driver's own crew) and PATCH .../status (driver
reports started/completed/no-show on their own run)."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def _seed_single_run_scenario(client, admin_headers, *, service_date="2026-09-01"):
    """One school, one driver+vehicle+crew, one run — the minimal
    scenario for exercising the driver endpoints in isolation."""
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Riverside Elementary", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Jordan Driver"}
    ).json()
    vehicle = client.post(
        "/vehicles",
        headers=admin_headers,
        json={"label": "Bus 101", "nominal_capacity": 48, "effective_capacity": 44},
    ).json()
    crew = client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": service_date,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    ).json()
    run = client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": service_date,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 420,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    ).json()
    return school, driver, vehicle, crew, run


def _login_as_driver(client, db_session, admin_headers, driver_id, *, email="driver1@example.org"):
    make_user(db_session, email=email, role=Role.DRIVER, driver_id=driver_id)
    token = login(client, email=email)
    return auth_headers(token)


def test_driver_my_assignments_returns_resolved_school_and_vehicle_names(
    client, admin_headers, db_session
):
    school, driver, vehicle, _crew, run = _seed_single_run_scenario(client, admin_headers)
    client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})

    driver_headers = _login_as_driver(client, db_session, admin_headers, driver["id"])
    response = client.get("/schedule/2026-09-01/my-assignments", headers=driver_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["run_id"] == run["id"]
    assert body[0]["school_name"] == school["name"]
    assert body[0]["vehicle_label"] == vehicle["label"]
    assert body[0]["status"] == "scheduled"
    assert body[0]["service_date"] == "2026-09-01"


def test_driver_my_assignments_excludes_another_drivers_runs(client, admin_headers, db_session):
    _school, _driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})

    other_driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Other Driver"}
    ).json()
    other_headers = _login_as_driver(
        client, db_session, admin_headers, other_driver["id"], email="driver2@example.org"
    )
    response = client.get("/schedule/2026-09-01/my-assignments", headers=other_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_driver_my_assignments_requires_driver_role(client, admin_headers, db_session):
    _seed_single_run_scenario(client, admin_headers)
    make_user(db_session, email="dispatcher2@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatcher2@example.org")
    response = client.get("/schedule/2026-09-01/my-assignments", headers=auth_headers(token))
    assert response.status_code == 403


def test_driver_my_assignments_requires_a_linked_driver_record(client, admin_headers, db_session):
    _seed_single_run_scenario(client, admin_headers)
    make_user(db_session, email="unlinked@example.org", role=Role.DRIVER)  # driver_id=None
    token = login(client, email="unlinked@example.org")
    response = client.get("/schedule/2026-09-01/my-assignments", headers=auth_headers(token))
    assert response.status_code == 403
    assert "not linked" in response.json()["detail"].lower()


def test_driver_can_update_own_assignment_status_and_it_is_audited(
    client, admin_headers, db_session
):
    _school, driver, _vehicle, _crew, run = _seed_single_run_scenario(client, admin_headers)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment_id = schedule.json()["assignments"][0]["id"]

    driver_headers = _login_as_driver(client, db_session, admin_headers, driver["id"])
    response = client.patch(
        f"/schedule/assignments/{assignment_id}/status",
        headers=driver_headers,
        json={"status": "in_progress"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["run_id"] == run["id"]

    completed = client.patch(
        f"/schedule/assignments/{assignment_id}/status",
        headers=driver_headers,
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    entries = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "assignment",
            AuditLogEntry.entity_id == assignment_id,
            AuditLogEntry.action == "status_changed",
        )
        .order_by(AuditLogEntry.id)
        .all()
    )
    assert len(entries) == 2
    assert entries[0].before_state["status"] == "scheduled"
    assert entries[0].after_state["status"] == "in_progress"
    assert entries[1].before_state["status"] == "in_progress"
    assert entries[1].after_state["status"] == "completed"
    assert all(e.actor_user_id is not None for e in entries)


def test_driver_cannot_update_another_drivers_assignment_status(client, admin_headers, db_session):
    _school, _driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment_id = schedule.json()["assignments"][0]["id"]

    other_driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Other Driver"}
    ).json()
    other_headers = _login_as_driver(
        client, db_session, admin_headers, other_driver["id"], email="driver2@example.org"
    )
    response = client.patch(
        f"/schedule/assignments/{assignment_id}/status",
        headers=other_headers,
        json={"status": "no_show"},
    )
    assert response.status_code == 403


def test_assignment_status_update_requires_driver_role(client, admin_headers):
    _school, _driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment_id = schedule.json()["assignments"][0]["id"]

    # admin_headers belongs to a transportation_admin, not a driver.
    response = client.patch(
        f"/schedule/assignments/{assignment_id}/status",
        headers=admin_headers,
        json={"status": "completed"},
    )
    assert response.status_code == 403


def test_assignment_status_update_rejects_invalid_status_value(client, admin_headers, db_session):
    _school, driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment_id = schedule.json()["assignments"][0]["id"]

    driver_headers = _login_as_driver(client, db_session, admin_headers, driver["id"])
    response = client.patch(
        f"/schedule/assignments/{assignment_id}/status",
        headers=driver_headers,
        json={"status": "on_the_moon"},
    )
    assert response.status_code == 422
