"""Reproduces the spec section 5 worked example end-to-end: persist a
school/vehicle/driver/crew/three runs via the API, call POST /schedule
as a dispatcher, and verify the solver's result was correctly persisted
as Assignments, is readable with correct RBAC scoping, and produced
audit trail entries.
"""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def _seed_spec_section5_scenario(client, admin_headers):
    school = client.post(
        "/schools", headers=admin_headers, json={"name": "Multi-level campus", "location_lat": 29.70, "location_lon": -95.40}
    ).json()

    client.post(
        "/qualifications", headers=admin_headers, json={"code": "CDL_B", "kind": "license"}
    )
    driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Jordan Driver", "qualification_codes": ["CDL_B"]}
    ).json()
    vehicle = client.post(
        "/vehicles", headers=admin_headers, json={"label": "Bus 101", "nominal_capacity": 48, "effective_capacity": 44}
    ).json()
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

    run_specs = [
        (360, 410, 40, 10, 12),  # Pre-K 6:00-6:50
        (420, 470, 40, 10, 35),  # HS 7:00-7:50
        (480, 540, 45, 15, 28),  # MS 8:00-9:00
    ]
    runs = []
    for earliest, latest, duration, buffer_, passengers in run_specs:
        run = client.post(
            "/runs",
            headers=admin_headers,
            json={
                "service_date": "2026-09-01",
                "school_id": school["id"],
                "window_earliest": earliest,
                "window_latest": latest,
                "duration_minutes": duration,
                "buffer_minutes": buffer_,
                "passenger_count": passengers,
            },
        ).json()
        runs.append(run)

    return school, driver, vehicle, crew, runs


def test_full_schedule_flow_persists_assignments_with_explanations(client, admin_headers, db_session):
    _school, _driver, _vehicle, crew, runs = _seed_spec_section5_scenario(client, admin_headers)

    response = client.post(
        "/schedule",
        headers=admin_headers,
        json={"service_date": "2026-09-01", "average_deadhead_speed_kmh": 40.0},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["crews_used"] == 1
    assert len(body["assignments"]) == 3
    for assignment in body["assignments"]:
        assert assignment["crew_id"] == crew["id"]
        assert "qualifications" in assignment["explanation_text"]

    # Persisted, not just returned: fetch again via the read endpoint.
    read_back = client.get(
        "/schedule/2026-09-01/assignments", headers=admin_headers
    )
    assert read_back.status_code == 200
    assert {a["run_id"] for a in read_back.json()} == {r["id"] for r in runs}


def test_schedule_endpoint_requires_dispatcher_or_admin_role(client, db_session, admin_headers):
    _seed_spec_section5_scenario(client, admin_headers)
    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.post(
        "/schedule", headers=auth_headers(token), json={"service_date": "2026-09-01"}
    )
    assert response.status_code == 403


def test_schedule_endpoint_reports_infeasible_clearly(client, admin_headers):
    school = client.post(
        "/schools", headers=admin_headers, json={"name": "S", "location_lat": 29.70, "location_lon": -95.40}
    ).json()
    driver = client.post("/drivers", headers=admin_headers, json={"full_name": "D"}).json()
    vehicle = client.post("/vehicles", headers=admin_headers, json={"label": "V"}).json()
    client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    )
    # A run requiring a qualification no crew has.
    client.post(
        "/qualifications", headers=admin_headers, json={"code": "lift", "kind": "vehicle_capability"}
    )
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "school_id": school["id"],
            "window_earliest": 360,
            "window_latest": 420,
            "duration_minutes": 40,
            "buffer_minutes": 10,
            "required_qualification_codes": ["lift"],
        },
    )
    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 422
    assert "qualified" in response.json()["detail"].lower()


def test_driver_only_sees_own_crews_assignments(client, admin_headers, db_session):
    _school, driver, _vehicle, crew, runs = _seed_spec_section5_scenario(client, admin_headers)
    client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})

    # This driver's User account is linked to the Driver record used above.
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER, driver_id=driver["id"])
    token = login(client, email="driver1@example.org")
    response = client.get("/schedule/2026-09-01/assignments", headers=auth_headers(token))
    assert response.status_code == 200
    assert len(response.json()) == 3  # all three runs, all on this driver's crew

    # A second, unrelated driver sees nothing for this date.
    make_user(db_session, email="driver2@example.org", role=Role.DRIVER)
    other_driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Other Driver"}
    ).json()
    from isd_api.models import User

    unrelated = db_session.query(User).filter(User.email == "driver2@example.org").one()
    unrelated.driver_id = other_driver["id"]
    db_session.commit()
    token2 = login(client, email="driver2@example.org")
    response2 = client.get("/schedule/2026-09-01/assignments", headers=auth_headers(token2))
    assert response2.status_code == 200
    assert response2.json() == []


def test_rescheduling_replaces_prior_assignments_and_audits_both(client, admin_headers, db_session):
    _seed_spec_section5_scenario(client, admin_headers)
    first = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert first.status_code == 200

    second = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert second.status_code == 200

    # Exactly one current assignment per run — re-scheduling must not
    # leave stale rows behind (note: we don't assert new row IDs differ
    # from the first run's, since PostgreSQL sequences never reuse a
    # deleted ID but SQLite's rowid allocator can — that's a storage
    # detail, not a behavior this API promises).
    current = client.get("/schedule/2026-09-01/assignments", headers=admin_headers).json()
    assert len(current) == 3
    assert len({a["run_id"] for a in current}) == 3

    entries = db_session.query(AuditLogEntry).filter(AuditLogEntry.entity_type == "assignment").all()
    actions = [e.action for e in entries]
    assert actions.count("created") == 6  # 3 from first run + 3 from second
    assert actions.count("deleted") == 3  # the first run's assignments, replaced by the second
    assert all(e.actor_user_id is not None for e in entries)
