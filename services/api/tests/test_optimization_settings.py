"""Configurable soft-constraint objective weights (spec section 2.2)."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user

SERVICE_DATE = "2026-09-01"


def _put(client, headers, crews=1, deadhead=0, buffer=0):
    return client.put(
        "/optimization-settings",
        headers=headers,
        json={
            "crews_used_weight": crews,
            "deadhead_minutes_weight": deadhead,
            "arrival_buffer_weight": buffer,
        },
    )


def _seed_two_far_schools_and_two_crews(client, admin_headers):
    schools = [
        client.post(
            "/schools",
            headers=admin_headers,
            json={"name": name, "location_lat": lat, "location_lon": -95.40},
        ).json()
        for name, lat in (("North Elementary", 29.70), ("South Middle", 29.80))
    ]
    # ~11 km apart: about 22 minutes of straight-line deadhead at 30 km/h.
    for school, (earliest, latest) in zip(schools, ((360, 410), (460, 520)), strict=True):
        client.post(
            "/runs",
            headers=admin_headers,
            json={
                "service_date": SERVICE_DATE,
                "school_id": school["id"],
                "direction": "am",
                "window_earliest": earliest,
                "window_latest": latest,
                "duration_minutes": 40,
                "buffer_minutes": 10,
            },
        )
    for label in ("A", "B"):
        driver = client.post(
            "/drivers", headers=admin_headers, json={"full_name": f"Driver {label}"}
        ).json()
        vehicle = client.post(
            "/vehicles", headers=admin_headers, json={"label": f"Bus {label}"}
        ).json()
        client.post(
            "/crews",
            headers=admin_headers,
            json={
                "service_date": SERVICE_DATE,
                "driver_id": driver["id"],
                "vehicle_id": vehicle["id"],
                "available_window_earliest": 0,
                "available_window_latest": 1439,
            },
        )


def _solve(client, headers):
    response = client.post("/schedule", headers=headers, json={"service_date": SERVICE_DATE})
    assert response.status_code == 200, response.text
    return response.json()


def test_defaults_are_reported_when_nothing_is_saved(client, admin_headers):
    body = client.get("/optimization-settings", headers=admin_headers).json()
    assert body == {
        "crews_used_weight": 1,
        "deadhead_minutes_weight": 0,
        "arrival_buffer_weight": 0,
        "is_default": True,
    }


def test_settings_round_trip_and_are_audited(client, admin_headers, db_session):
    response = _put(client, admin_headers, crews=100, deadhead=3, buffer=2)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "crews_used_weight": 100,
        "deadhead_minutes_weight": 3,
        "arrival_buffer_weight": 2,
        "is_default": False,
    }
    assert (
        client.get("/optimization-settings", headers=admin_headers).json()["crews_used_weight"]
        == 100
    )

    # A second save updates the single row rather than adding another.
    _put(client, admin_headers, crews=5, deadhead=0, buffer=0)
    assert (
        client.get("/optimization-settings", headers=admin_headers).json()["crews_used_weight"] == 5
    )

    entries = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "optimization_settings")
        .order_by(AuditLogEntry.id)
        .all()
    )
    assert len(entries) == 2
    assert "is_default" not in entries[0].before_state  # derived, not a setting
    assert entries[0].before_state["crews_used_weight"] == 1
    assert entries[0].after_state["crews_used_weight"] == 100
    assert entries[1].before_state["crews_used_weight"] == 100


def test_invalid_weights_are_rejected(client, admin_headers):
    for payload in (
        {"crews_used_weight": -1, "deadhead_minutes_weight": 0, "arrival_buffer_weight": 0},
        {"crews_used_weight": 1001, "deadhead_minutes_weight": 0, "arrival_buffer_weight": 0},
        {"crews_used_weight": 0, "deadhead_minutes_weight": 0, "arrival_buffer_weight": 0},
        {"crews_used_weight": 1, "deadhead_minutes_weight": 0},
        {"crews_used_weight": 1.5, "deadhead_minutes_weight": 0, "arrival_buffer_weight": 0},
    ):
        response = client.put("/optimization-settings", headers=admin_headers, json=payload)
        assert response.status_code == 422, (payload, response.text)
    assert client.get("/optimization-settings", headers=admin_headers).json()["is_default"] is True


def test_only_a_transportation_admin_may_change_settings_but_dispatchers_can_read(
    client, admin_headers, db_session
):
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    make_user(db_session, email="drv@example.org", role=Role.DRIVER)
    dispatcher = auth_headers(login(client, email="disp@example.org"))
    driver = auth_headers(login(client, email="drv@example.org"))

    assert client.get("/optimization-settings", headers=dispatcher).status_code == 200
    assert _put(client, dispatcher, crews=9).status_code == 403
    assert client.get("/optimization-settings", headers=driver).status_code == 403
    assert _put(client, driver, crews=9).status_code == 403
    assert client.get("/optimization-settings").status_code in (401, 403)
    assert client.get("/optimization-settings", headers=admin_headers).json()["is_default"] is True


def test_saved_weights_change_a_real_schedule_solve(client, admin_headers):
    _seed_two_far_schools_and_two_crews(client, admin_headers)

    # Defaults: minimize crews only, so both runs chain onto one crew.
    default_result = _solve(client, admin_headers)
    assert default_result["crews_used"] == 1
    assert default_result["total_deadhead_minutes"] > 0

    # Deadhead now outweighs saving a crew: split across two crews, no deadhead.
    _put(client, admin_headers, crews=10, deadhead=1)
    weighted = _solve(client, admin_headers)
    assert weighted["crews_used"] == 2
    assert weighted["total_deadhead_minutes"] == 0

    # A dominant crews weight restores the single-crew chain.
    _put(client, admin_headers, crews=1000, deadhead=1)
    assert _solve(client, admin_headers)["crews_used"] == 1


def test_arrival_buffer_weight_moves_assignments_earlier(client, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Solo Elementary", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": SERVICE_DATE,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 500,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    )
    driver = client.post("/drivers", headers=admin_headers, json={"full_name": "Driver S"}).json()
    vehicle = client.post("/vehicles", headers=admin_headers, json={"label": "Bus S"}).json()
    client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": SERVICE_DATE,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    )

    _put(client, admin_headers, crews=1, buffer=1)
    result = _solve(client, admin_headers)
    (assignment,) = result["assignments"]
    assert (assignment["start_minute"], assignment["end_minute"]) == (360, 410)
    assert result["total_arrival_buffer_minutes"] == 500 - 410
