"""Turn-by-turn directions for a run's stops today (spec section 9):
GET /schedule/assignments/{id}/directions. ORS is faked; no live key."""

import pytest
from isd_solver import Directions, DirectionsError, DirectionStep, Leg

from isd_api.models import Role
from isd_api.routers import schedule
from tests.conftest import auth_headers, login, make_user
from tests.test_route_stops import _crew, _set_stops, _stop, _student

DAY = "2026-10-05"


@pytest.fixture(autouse=True)
def _empty_cache():
    schedule._directions_cache.clear()


def _setup(client, h, db_session):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    far = _stop(client, h, "Far", 29.74)
    mid = _stop(client, h, "Mid", 29.72)
    near = _stop(client, h, "Near", 29.71)
    route = client.post(
        "/route-templates",
        headers=h,
        json={
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 420,
            "window_latest": 500,
            "duration_minutes": 40,
            "days_of_week": [0, 1, 2, 3, 4],
        },
    ).json()
    _set_stops(client, h, route, (far, 0), (mid, 5), (near, 10))
    _student(client, h, school, "Ana", far)
    _student(client, h, school, "Cy", near)  # nobody at Mid: skipped today
    driver, driver_headers = _crew(client, h, "A", db_session)
    client.post(f"/schedule/{DAY}/generate-from-templates", headers=h)
    [assignment] = client.post("/schedule", headers=h, json={"service_date": DAY}).json()[
        "assignments"
    ]
    return assignment, driver_headers


def _directions(client, headers, assignment, **params):
    return client.get(
        f"/schedule/assignments/{assignment['id']}/directions", headers=headers, params=params
    )


@pytest.fixture()
def ors(monkeypatch):
    calls = []
    state = {"error": None}

    def fake(api_key, waypoints, vehicle, **kwargs):
        calls.append({"key": api_key, "waypoints": waypoints, "vehicle": vehicle, **kwargs})
        if state["error"] is not None:
            raise state["error"]
        return Directions(
            distance_m=5000.0,
            duration_s=600.0,
            coordinates=[(w.lat, w.lon) for w in waypoints],
            legs=[Leg(2500.0, 300.0) for _ in waypoints[1:]],
            steps=[
                DirectionStep(f"Head to waypoint {i + 1}", "Oak Street", 2500.0, 300.0, i)
                for i in range(len(waypoints) - 1)
            ],
        )

    monkeypatch.setattr(schedule.settings, "ors_api_key", "test-key")
    monkeypatch.setattr(schedule, "ors_directions", fake)
    return {"calls": calls, "state": state}


def test_without_a_key_the_stop_order_is_still_given(
    client, admin_headers, db_session, monkeypatch
):
    monkeypatch.setattr(schedule.settings, "ors_api_key", None)
    assignment, driver = _setup(client, admin_headers, db_session)
    body = _directions(client, driver, assignment).json()
    assert body["available"] is False
    assert "OpenRouteService key" in body["reason"]
    # The morning: today's stops (Mid skipped, nobody riding), then school.
    assert [w["label"] for w in body["waypoints"]] == ["Far", "Near", "Riverside"]


def test_directions_follow_todays_stops_with_the_buses_dimensions(
    client, admin_headers, db_session, ors
):
    assignment, driver = _setup(client, admin_headers, db_session)
    client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            "location_lat": 29.73,
            "location_lon": -95.40,
            "category": "frequent_flooding",
            "note": "Low water crossing",
        },
    )
    response = _directions(client, driver, assignment)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is True
    assert [leg["to_label"] for leg in body["legs"]] == ["Near", "Riverside"]
    assert [(s["instruction"], s["leg"]) for s in body["steps"]] == [
        ("Head to waypoint 1", 0),
        ("Head to waypoint 2", 1),
    ]
    assert body["coordinates"][0] == [29.74, -95.40]
    assert "openrouteservice" in body["attribution"]
    [call] = ors["calls"]
    assert call["key"] == "test-key"
    assert [(w.lat, w.lon) for w in call["waypoints"]] == [
        (29.74, -95.40),
        (29.71, -95.40),
        (29.70, -95.40),
    ]
    assert [(p.lat, p.lon) for p in call["avoid_points"]] == [(29.73, -95.40)]


def test_directions_use_the_configured_routing_server_and_profile(
    client, admin_headers, db_session, ors, monkeypatch
):
    """A self-hosted OpenRouteService (ISD_API_ORS_BASE_URL) serves the
    drivers' directions too, not only the scheduler's travel times."""
    monkeypatch.setattr(schedule.settings, "ors_base_url", "http://ors.internal:8082/ors")
    monkeypatch.setattr(schedule.settings, "ors_profile", "driving-car")
    assignment, driver = _setup(client, admin_headers, db_session)
    assert _directions(client, driver, assignment).status_code == 200
    [call] = ors["calls"]
    assert call["base_url"] == "http://ors.internal:8082/ors"
    assert call["profile"] == "driving-car"


def test_the_driver_can_start_from_where_they_are(client, admin_headers, db_session, ors):
    assignment, driver = _setup(client, admin_headers, db_session)
    body = _directions(client, driver, assignment, from_lat=29.8, from_lon=-95.5).json()
    assert [w["label"] for w in body["waypoints"]][0] == "Your position"
    assert body["legs"][0]["to_label"] == "Far"
    half = _directions(client, driver, assignment, from_lat=29.8)
    assert half.status_code == 422


def test_directions_are_cached_for_a_while(client, admin_headers, db_session, ors):
    assignment, driver = _setup(client, admin_headers, db_session)
    _directions(client, driver, assignment)
    _directions(client, driver, assignment)
    assert len(ors["calls"]) == 1


def test_an_ors_failure_says_to_follow_the_stop_order(client, admin_headers, db_session, ors):
    ors["state"]["error"] = DirectionsError("timed out")
    assignment, driver = _setup(client, admin_headers, db_session)
    response = _directions(client, driver, assignment)
    assert response.status_code == 502
    assert "Follow the stop order" in response.json()["detail"]


def test_only_the_runs_driver_and_dispatch_get_directions(client, admin_headers, db_session, ors):
    assignment, driver = _setup(client, admin_headers, db_session)
    _, other_driver = _crew(client, admin_headers, "B", db_session)
    make_user(db_session, email="office@example.org", role=Role.SCHOOL_ADMIN)
    office = auth_headers(login(client, email="office@example.org"))
    assert _directions(client, driver, assignment).status_code == 200
    assert _directions(client, admin_headers, assignment).status_code == 200
    assert _directions(client, other_driver, assignment).status_code == 403
    assert _directions(client, office, assignment).status_code == 403
