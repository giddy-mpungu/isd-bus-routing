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
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Jordan Driver"},
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
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Other Driver"},
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
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Other Driver"},
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


# --- Roster (spec section 9 "Stops"/"Authorized student information") ---
# GET .../my-assignments and PATCH .../status both embed an unordered,
# stop-grouped list of expected riders -- deliberately not a sequenced
# stop order, which needs a stop-sequence model this system doesn't have.


def _add_student(
    client, admin_headers, *, school_id, full_name, stop_id=None, default_ridership="rides"
):
    payload = {
        "full_name": full_name,
        "school_id": school_id,
        "default_ridership": default_ridership,
    }
    if stop_id is not None:
        payload["stop_id"] = stop_id
    return client.post("/students", headers=admin_headers, json=payload).json()


def test_my_assignments_roster_groups_riders_by_stop(client, admin_headers, db_session):
    school, driver, _vehicle, _crew, run = _seed_single_run_scenario(client, admin_headers)
    stop_a = client.post(
        "/stops",
        headers=admin_headers,
        json={"label": "Elm St", "location_lat": 1, "location_lon": 1},
    ).json()
    stop_b = client.post(
        "/stops",
        headers=admin_headers,
        json={"label": "Oak St", "location_lat": 2, "location_lon": 2},
    ).json()
    _add_student(
        client, admin_headers, school_id=school["id"], full_name="Ana", stop_id=stop_a["id"]
    )
    _add_student(
        client, admin_headers, school_id=school["id"], full_name="Ben", stop_id=stop_a["id"]
    )
    _add_student(
        client, admin_headers, school_id=school["id"], full_name="Cy", stop_id=stop_b["id"]
    )
    _add_student(client, admin_headers, school_id=school["id"], full_name="Dee")  # no stop
    _add_student(
        client,
        admin_headers,
        school_id=school["id"],
        full_name="Not Riding",
        stop_id=stop_a["id"],
        default_ridership="does_not_ride",
    )
    client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})

    driver_headers = _login_as_driver(client, db_session, admin_headers, driver["id"])
    response = client.get("/schedule/2026-09-01/my-assignments", headers=driver_headers)
    assert response.status_code == 200, response.text
    body = response.json()[0]
    assert body["roster_ambiguous"] is False
    stops = {s["stop_label"]: sorted(s["student_names"]) for s in body["stops"]}
    assert stops == {"Elm St": ["Ana", "Ben"], "Oak St": ["Cy"], None: ["Dee"]}
    assert run["id"] == body["run_id"]


def test_my_assignments_roster_is_empty_and_flagged_when_ambiguous(
    client, admin_headers, db_session
):
    school, driver, vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    # A second run for the same school/date/direction makes ridership
    # unattributable to either one specifically.
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 460,
            "window_latest": 520,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    )
    driver2 = client.post(
        "/drivers", headers=admin_headers, json={"license_class": "cdl_a", "full_name": "Driver 2"}
    ).json()
    vehicle2 = client.post("/vehicles", headers=admin_headers, json={"label": "Bus 202"}).json()
    client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "driver_id": driver2["id"],
            "vehicle_id": vehicle2["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    )
    _add_student(client, admin_headers, school_id=school["id"], full_name="Ana")
    client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})

    # Either crew could end up with either or both runs (a solver tie
    # between interchangeable crews, not something this test should
    # assume) -- check whichever assignments exist across both drivers.
    driver_headers = _login_as_driver(client, db_session, admin_headers, driver["id"])
    driver2_headers = _login_as_driver(
        client, db_session, admin_headers, driver2["id"], email="driver2@example.org"
    )
    all_bodies = [
        *client.get("/schedule/2026-09-01/my-assignments", headers=driver_headers).json(),
        *client.get("/schedule/2026-09-01/my-assignments", headers=driver2_headers).json(),
    ]
    assert len(all_bodies) == 2
    for body in all_bodies:
        assert body["roster_ambiguous"] is True
        assert body["stops"] == []


def test_my_assignments_roster_is_empty_when_no_students_ride(client, admin_headers, db_session):
    _school, driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})

    driver_headers = _login_as_driver(client, db_session, admin_headers, driver["id"])
    response = client.get("/schedule/2026-09-01/my-assignments", headers=driver_headers)
    body = response.json()[0]
    assert body["roster_ambiguous"] is False
    assert body["stops"] == []


def test_status_update_response_also_includes_the_roster(client, admin_headers, db_session):
    school, driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    stop = client.post(
        "/stops",
        headers=admin_headers,
        json={"label": "Elm St", "location_lat": 1, "location_lon": 1},
    ).json()
    _add_student(client, admin_headers, school_id=school["id"], full_name="Ana", stop_id=stop["id"])
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment_id = schedule.json()["assignments"][0]["id"]

    driver_headers = _login_as_driver(client, db_session, admin_headers, driver["id"])
    response = client.patch(
        f"/schedule/assignments/{assignment_id}/status",
        headers=driver_headers,
        json={"status": "in_progress"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["stops"] == [{"stop_label": "Elm St", "student_names": ["Ana"]}]
