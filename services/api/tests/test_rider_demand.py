"""A bus must have a seat for every rider (spec section 15): the capacity
checks count the day's riders (defaults and overrides), not only the
passenger count typed on a run, which is 0 for runs made from templates."""

from datetime import UTC, datetime

import pytest

DAY = "2026-08-01"


@pytest.fixture()
def clock(monkeypatch):
    """6 am in the district (America/Chicago, UTC-5 in August) on DAY."""
    moment = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
    monkeypatch.setattr("isd_api.ridership_rules.utc_now", lambda: moment)


def _school(client, h):
    return client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()


def _students(client, h, school, n, ridership="rides"):
    return [
        client.post(
            "/students",
            headers=h,
            json={
                "full_name": f"Rider {i}",
                "school_id": school["id"],
                "default_ridership": ridership,
            },
        ).json()
        for i in range(n)
    ]


def _crew(client, h, label, seats):
    driver = client.post(
        "/drivers", headers=h, json={"full_name": f"Driver of {label}", "license_class": "cdl_a"}
    ).json()
    body = {"label": label}
    if seats is not None:
        body |= {"nominal_capacity": seats, "effective_capacity": seats}
    vehicle = client.post("/vehicles", headers=h, json=body).json()
    return client.post(
        "/crews",
        headers=h,
        json={
            "service_date": DAY,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 360,
            "available_window_latest": 1000,
        },
    ).json()


def _run(client, h, school, passenger_count=0):
    return client.post(
        "/runs",
        headers=h,
        json={
            "service_date": DAY,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 450,
            "window_latest": 480,
            "duration_minutes": 30,
            "passenger_count": passenger_count,
        },
    ).json()


def _solve(client, h):
    response = client.post("/schedule", headers=h, json={"service_date": DAY})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_solver_seats_every_rider_though_no_count_was_typed(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    _students(client, h, school, 3)
    _students(client, h, school, 2, ridership="does_not_ride")
    van = _crew(client, h, "Van 3", 2)
    bus = _crew(client, h, "Bus 7", 40)
    run = _run(client, h, school)
    assert run["passenger_count"] == 0

    [assignment] = _solve(client, h)["assignments"]
    assert assignment["crew_id"] == bus["id"]

    # Moving it onto the van by hand is refused too.
    response = client.patch(
        f"/schedule/assignments/{assignment['id']}", headers=h, json={"crew_id": van["id"]}
    )
    assert response.status_code == 422, response.text
    assert "insufficient for 3 expected passenger(s)" in response.text


def _refused(client, h):
    response = client.post("/schedule", headers=h, json={"service_date": DAY})
    assert response.status_code == 422, response.text
    return response.json()["detail"]


def test_no_bus_big_enough_and_the_solve_says_why(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    _students(client, h, school, 3)
    _crew(client, h, "Van 3", 2)
    _run(client, h, school)
    assert "enough vehicle capacity for 3 expected passengers" in _refused(client, h)


def test_a_higher_typed_count_still_counts(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    _students(client, h, school, 1)
    _crew(client, h, "Van 3", 2)
    _run(client, h, school, passenger_count=5)
    assert "enough vehicle capacity for 5 expected passengers" in _refused(client, h)


def test_riders_who_cant_be_pinned_to_one_run_fall_back_to_the_typed_count(client, admin_headers):
    """Two runs on the leg and no stop lists: nobody knows which bus a
    rider takes, so the system doesn't guess (isd_api/routes.py)."""
    h = admin_headers
    school = _school(client, h)
    _students(client, h, school, 3)
    _crew(client, h, "Van 3", 2)
    _crew(client, h, "Van 4", 2)
    _run(client, h, school)
    _run(client, h, school)
    assert len(_solve(client, h)["assignments"]) == 2


def test_more_riders_after_scheduling_raise_an_alert_and_bigger_buses_are_offered(
    client, admin_headers, clock
):
    h = admin_headers
    school = _school(client, h)
    _students(client, h, school, 2)
    _crew(client, h, "Van 3", 2)
    _run(client, h, school)
    [assignment] = _solve(client, h)["assignments"]

    # A third child starts riding.
    _students(client, h, school, 1)
    alerts = client.get("/alerts", headers=h, params={"service_date": DAY}).json()["alerts"]
    [over] = [a for a in alerts if a["kind"] == "over_capacity"]
    assert over["severity"] == "critical"
    assert over["entity_id"] == assignment["id"]
    assert "Van 3 has 2 seats for 3 expected riders" in over["message"]

    # Spare buses: big enough only, and never one of unknown size.
    for label, seats in (("Bus 7", 40), ("Van 5", 2), ("Bus 9", None)):
        size = {} if seats is None else {"nominal_capacity": seats, "effective_capacity": seats}
        client.post("/vehicles", headers=h, json={"label": label, **size})
    spares = client.get(f"/assignments/{assignment['id']}/spare-vehicles", headers=h)
    assert spares.status_code == 200, spares.text
    assert [s["label"] for s in spares.json()["spares"]] == ["Bus 7"]


def test_a_vehicles_type_wheelchair_positions_and_turning_radius_are_kept(client, admin_headers):
    h = admin_headers
    vehicle = client.post(
        "/vehicles",
        headers=h,
        json={
            "label": "Bus 12",
            "nominal_capacity": 40,
            "vehicle_type": "type_c",
            "wheelchair_positions": 2,
            "turning_radius_m": 12.5,
        },
    ).json()
    assert (vehicle["vehicle_type"], vehicle["wheelchair_positions"]) == ("type_c", 2)
    updated = client.patch(
        f"/vehicles/{vehicle['id']}",
        headers=h,
        json={"vehicle_type": "type_d", "wheelchair_positions": None},
    ).json()
    assert updated["vehicle_type"] == "type_d"
    assert updated["wheelchair_positions"] is None
    assert updated["turning_radius_m"] == 12.5


def test_a_rider_in_a_wheelchair_needs_a_bus_with_a_position(client, admin_headers, clock):
    h = admin_headers
    client.post(
        "/qualifications",
        headers=h,
        json={
            "code": "wheelchair",
            "kind": "vehicle_capability",
            "takes_wheelchair_position": True,
        },
    )
    school = _school(client, h)
    client.post(
        "/students",
        headers=h,
        json={
            "full_name": "Rider in a wheelchair",
            "school_id": school["id"],
            "accommodation_codes": ["wheelchair"],
        },
    )

    def crew(label, positions):
        driver = client.post(
            "/drivers", headers=h, json={"full_name": f"Driver {label}", "license_class": "cdl_a"}
        ).json()
        body = {"label": label, "nominal_capacity": 40, "qualification_codes": ["wheelchair"]}
        if positions is not None:
            body["wheelchair_positions"] = positions
        vehicle = client.post("/vehicles", headers=h, json=body).json()
        return client.post(
            "/crews",
            headers=h,
            json={
                "service_date": DAY,
                "driver_id": driver["id"],
                "vehicle_id": vehicle["id"],
                "available_window_earliest": 360,
                "available_window_latest": 1000,
            },
        ).json()

    unrecorded = crew("Bus 7", None)
    _run(client, h, school)
    assert "enough wheelchair positions for 1" in _refused(client, h)

    with_one = crew("Bus 12", 1)
    [assignment] = _solve(client, h)["assignments"]
    assert assignment["crew_id"] == with_one["id"]
    response = client.patch(
        f"/schedule/assignments/{assignment['id']}", headers=h, json={"crew_id": unrecorded["id"]}
    )
    assert response.status_code == 422
    assert "wheelchair position(s) for 1 rider(s) in a wheelchair" in response.json()["detail"]
