"""ADR 0009: driver-reported GPS position, the dispatcher fleet view
(spec section 17), and the family bus-position read (spec section 18).
"""

from isd_api.models import Role, User
from tests.conftest import auth_headers, login, make_user


def _seed_single_run_scenario(client, admin_headers, *, service_date="2026-09-01"):
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


def _login_as_driver(client, db_session, driver_id, *, email="driver1@example.org"):
    make_user(db_session, email=email, role=Role.DRIVER, driver_id=driver_id)
    token = login(client, email=email)
    return auth_headers(token)


def test_driver_reports_position_and_fleet_view_sees_it(client, admin_headers, db_session):
    _school, driver, vehicle, crew, _run = _seed_single_run_scenario(client, admin_headers)
    driver_headers = _login_as_driver(client, db_session, driver["id"])

    response = client.put(
        f"/drivers/{driver['id']}/position",
        headers=driver_headers,
        json={
            "service_date": "2026-09-01",
            "location_lat": 29.71,
            "location_lon": -95.41,
            "recorded_at": "2026-09-01T12:00:00Z",
        },
    )
    assert response.status_code == 204, response.text

    fleet = client.get("/schedule/2026-09-01/fleet-positions", headers=admin_headers)
    assert fleet.status_code == 200, fleet.text
    body = fleet.json()
    assert len(body) == 1
    assert body[0]["crew_id"] == crew["id"]
    assert body[0]["driver_full_name"] == "Jordan Driver"
    assert body[0]["vehicle_label"] == vehicle["label"]
    assert body[0]["location_lat"] == 29.71
    assert body[0]["location_lon"] == -95.41


def test_reporting_position_again_overwrites_not_duplicates(client, admin_headers, db_session):
    _school, driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    driver_headers = _login_as_driver(client, db_session, driver["id"])

    for lon in (-95.41, -95.42):
        response = client.put(
            f"/drivers/{driver['id']}/position",
            headers=driver_headers,
            json={
                "service_date": "2026-09-01",
                "location_lat": 29.71,
                "location_lon": lon,
                "recorded_at": "2026-09-01T12:00:00Z",
            },
        )
        assert response.status_code == 204

    fleet = client.get("/schedule/2026-09-01/fleet-positions", headers=admin_headers)
    body = fleet.json()
    assert len(body) == 1
    assert body[0]["location_lon"] == -95.42


def test_driver_cannot_report_another_drivers_position(client, admin_headers, db_session):
    _school, driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    other_driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Other Driver"},
    ).json()
    other_headers = _login_as_driver(
        client, db_session, other_driver["id"], email="driver2@example.org"
    )

    response = client.put(
        f"/drivers/{driver['id']}/position",
        headers=other_headers,
        json={
            "service_date": "2026-09-01",
            "location_lat": 29.71,
            "location_lon": -95.41,
            "recorded_at": "2026-09-01T12:00:00Z",
        },
    )
    assert response.status_code == 403


def test_driver_with_no_crew_that_date_gets_404(client, admin_headers, db_session):
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Unscheduled Driver"},
    ).json()
    driver_headers = _login_as_driver(client, db_session, driver["id"])

    response = client.put(
        f"/drivers/{driver['id']}/position",
        headers=driver_headers,
        json={
            "service_date": "2026-09-01",
            "location_lat": 29.71,
            "location_lon": -95.41,
            "recorded_at": "2026-09-01T12:00:00Z",
        },
    )
    assert response.status_code == 404


def test_fleet_positions_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    _seed_single_run_scenario(client, admin_headers)
    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.get("/schedule/2026-09-01/fleet-positions", headers=auth_headers(token))
    assert response.status_code == 403


def _seed_student(client, admin_headers, school_id):
    return client.post(
        "/students",
        headers=admin_headers,
        json={"full_name": "Riding Kid", "school_id": school_id},
    ).json()


def test_bus_position_unavailable_before_any_position_is_reported(
    client, admin_headers, db_session
):
    school, _driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    student = _seed_student(client, admin_headers, school["id"])
    client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})

    make_user(db_session, email="parent1@example.org", role=Role.PARENT)
    parent_token = login(client, email="parent1@example.org")
    parent_headers = auth_headers(parent_token)
    client.post(
        f"/students/{student['id']}/guardians",
        headers=admin_headers,
        json={"user_id": _find_user_id(db_session, "parent1@example.org")},
    )

    response = client.get(
        f"/students/{student['id']}/bus-position",
        headers=parent_headers,
        params={"service_date": "2026-09-01", "direction": "am"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is False
    assert body["ambiguous"] is False


def test_bus_position_available_after_driver_reports(client, admin_headers, db_session):
    school, driver, vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    student = _seed_student(client, admin_headers, school["id"])
    client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})

    driver_headers = _login_as_driver(client, db_session, driver["id"])
    client.put(
        f"/drivers/{driver['id']}/position",
        headers=driver_headers,
        json={
            "service_date": "2026-09-01",
            "location_lat": 29.712345,
            "location_lon": -95.418765,
            "recorded_at": "2026-09-01T12:00:00Z",
        },
    )

    make_user(db_session, email="parent2@example.org", role=Role.PARENT)
    parent_token = login(client, email="parent2@example.org")
    client.post(
        f"/students/{student['id']}/guardians",
        headers=admin_headers,
        json={"user_id": _find_user_id(db_session, "parent2@example.org")},
    )

    response = client.get(
        f"/students/{student['id']}/bus-position",
        headers=auth_headers(parent_token),
        params={"service_date": "2026-09-01", "direction": "am"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is True
    assert body["ambiguous"] is False
    # Spec section 18: approximate (about 100 m) and no driver identity.
    assert body["location_lat"] == 29.712
    assert body["location_lon"] == -95.419
    assert "driver_full_name" not in body
    assert "Jordan" not in response.text
    assert body["vehicle_label"] == vehicle["label"]


def test_bus_position_ambiguous_when_multiple_runs_share_school_date_direction(
    client, admin_headers, db_session
):
    school, _driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    # A second bus for the same school/date/direction.
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 420,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    )
    student = _seed_student(client, admin_headers, school["id"])

    make_user(db_session, email="parent3@example.org", role=Role.PARENT)
    parent_token = login(client, email="parent3@example.org")
    client.post(
        f"/students/{student['id']}/guardians",
        headers=admin_headers,
        json={"user_id": _find_user_id(db_session, "parent3@example.org")},
    )

    response = client.get(
        f"/students/{student['id']}/bus-position",
        headers=auth_headers(parent_token),
        params={"service_date": "2026-09-01", "direction": "am"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is False
    assert body["ambiguous"] is True


def test_bus_position_requires_self_or_guardian(client, admin_headers, db_session):
    school, _driver, _vehicle, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    student = _seed_student(client, admin_headers, school["id"])

    make_user(db_session, email="stranger@example.org", role=Role.PARENT)
    token = login(client, email="stranger@example.org")
    response = client.get(
        f"/students/{student['id']}/bus-position",
        headers=auth_headers(token),
        params={"service_date": "2026-09-01", "direction": "am"},
    )
    assert response.status_code == 403


def _find_user_id(db_session, email: str) -> int:
    return db_session.query(User).filter(User.email == email).one().id
