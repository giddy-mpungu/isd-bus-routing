"""The routing engine, part 2: approved turnarounds (spec section 7: dead
ends only with one the bus fits), difficult intersections and unsafe turns
as costs rather than avoids (section 8), and the district's turn costs.
The engine is faked; services/routing is exercised by the e2e checks."""

import pytest
from isd_solver import Directions, DirectionStep, Leg, TurnRules, UTurn

from isd_api.routers import schedule
from tests.test_directions import _directions, _empty_cache, _setup  # noqa: F401

ENGINE = "http://routing:8989"


def _knowledge(client, h, category, lat, lon, **extra):
    return client.post(
        "/geographic-knowledge",
        headers=h,
        json={
            "location_lat": lat,
            "location_lon": lon,
            "category": category,
            "note": f"{category} (test)",
            **extra,
        },
    )


def test_an_approved_turnaround_says_the_longest_bus_that_fits(client, admin_headers):
    h = admin_headers
    missing = _knowledge(client, h, "approved_turnaround", 29.759, -95.385)
    assert missing.status_code == 400
    assert "longest bus" in missing.json()["detail"]
    wrong = _knowledge(
        client,
        h,
        "approved_turnaround",
        29.759,
        -95.385,
        max_allowed_value=12,
        restricted_dimension="height_m",
    )
    assert wrong.status_code == 400

    made = _knowledge(client, h, "approved_turnaround", 29.759, -95.385, max_allowed_value=12)
    assert made.status_code == 201, made.text
    assert (made.json()["restricted_dimension"], made.json()["max_allowed_value"]) == (
        "length_m",
        12,
    )


@pytest.fixture()
def engine(monkeypatch):
    monkeypatch.setattr(schedule.settings, "routing_engine_url", ENGINE)
    monkeypatch.setattr(schedule.settings, "ors_api_key", None)
    state = {"u_turns": [], "calls": []}

    def fake(url, waypoints, vehicle, **kwargs):
        state["calls"].append(kwargs)
        return Directions(
            distance_m=5000.0,
            duration_s=600.0,
            coordinates=[(w.lat, w.lon) for w in waypoints],
            legs=[Leg(2500.0, 300.0) for _ in waypoints[1:]],
            steps=[DirectionStep("Continue", "Oak Street", 2500.0, 300.0, 0)],
            u_turns=state["u_turns"],
        )

    monkeypatch.setattr(schedule, "graphhopper_directions", fake)
    return state


def _bus_length(client, h, length):
    [vehicle] = client.get("/vehicles", headers=h).json()
    assert (
        client.patch(f"/vehicles/{vehicle['id']}", headers=h, json={"length_m": length}).status_code
        == 200
    )


def test_turning_round_anywhere_but_a_turnaround_the_bus_fits_is_flagged(
    client, admin_headers, db_session, engine
):
    h = admin_headers
    assignment, driver = _setup(client, h, db_session)
    _bus_length(client, h, 12.2)
    _knowledge(client, h, "approved_turnaround", 29.7591, -95.3852, max_allowed_value=13)
    _knowledge(client, h, "approved_turnaround", 29.7600, -95.3896, max_allowed_value=9)
    engine["u_turns"] = [
        UTurn(29.75911, -95.385236, "Rhode Place"),  # fits: nothing to say
        UTurn(29.760014, -95.389604, "Buffalo Terrace"),  # too small for this bus
        UTurn(29.767179, -95.399211, "Hartman Street"),  # no turnaround
    ]
    body = _directions(client, driver, assignment).json()
    assert body["warnings"] == [
        "Turns round on Buffalo Terrace, at a turnaround approved for buses up to 9 m; "
        "this bus is 12.2 m. Check with dispatch.",
        "Turns round on Hartman Street, which isn't an approved turnaround. "
        "Check with dispatch before going this way.",
    ]
    assert "GraphHopper" in body["attribution"]

    schedule._directions_cache.clear()
    spanish = _directions(client, {**driver, "Accept-Language": "es"}, assignment).json()
    assert spanish["warnings"][1].startswith("Da la vuelta en Hartman Street")


def test_difficult_places_are_costs_with_the_engine_and_avoids_without(
    client, admin_headers, db_session, engine, monkeypatch
):
    h = admin_headers
    assignment, driver = _setup(client, h, db_session)
    _knowledge(client, h, "difficult_intersection", 29.742, -95.398)
    _knowledge(client, h, "frequent_flooding", 29.73, -95.40)
    _directions(client, driver, assignment)
    [kwargs] = engine["calls"]
    assert [(p.lat, p.lon) for p in kwargs["slow_points"]] == [(29.742, -95.398)]
    assert [(p.lat, p.lon) for p in kwargs["avoid_points"]] == [(29.73, -95.40)]
    assert kwargs["turn_rules"] == TurnRules()

    # The district's own turn costs reach the engine.
    settings = client.get("/optimization-settings", headers=h).json()
    settings.pop("is_default")
    saved = client.put(
        "/optimization-settings", headers=h, json={**settings, "turn_left_seconds": 45}
    )
    assert saved.status_code == 200, saved.text
    schedule._directions_cache.clear()
    _directions(client, driver, assignment)
    assert engine["calls"][-1]["turn_rules"].left_s == 45
