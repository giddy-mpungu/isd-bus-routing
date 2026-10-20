"""A field trip that leaves from one of the district's schools (spec section
12.1 and 12.3): conflicts allow for the drive to the day's other schools,
and the driver gets turn-by-turn directions there and back."""

import pytest
from isd_solver import Directions, DirectionStep, Leg

from isd_api.models import Role
from isd_api.routers import schedule
from tests.conftest import auth_headers, login, make_user

DAY = "2026-10-06"


@pytest.fixture(autouse=True)
def _empty_cache():
    schedule._directions_cache.clear()


def _school(client, h, name, lat):
    return client.post(
        "/schools", headers=h, json={"name": name, "location_lat": lat, "location_lon": -95.40}
    ).json()


def _day(client, h):
    """North and South Schools about 11 km apart (some 22 minutes at the
    straight-line estimate); Pat drives South's 13:50 run."""
    north = _school(client, h, "North School", 29.70)
    south = _school(client, h, "South School", 29.80)
    driver = client.post(
        "/drivers", headers=h, json={"full_name": "Pat", "license_class": "cdl_a"}
    ).json()
    vehicle = client.post(
        "/vehicles", headers=h, json={"label": "Bus 7", "nominal_capacity": 40}
    ).json()
    client.post(
        "/crews",
        headers=h,
        json={
            "service_date": DAY,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 300,
            "available_window_latest": 1200,
        },
    )
    client.post(
        "/runs",
        headers=h,
        json={
            "service_date": DAY,
            "school_id": south["id"],
            "direction": "pm",
            "window_earliest": 830,
            "window_latest": 860,
            "duration_minutes": 30,
        },
    )
    assert client.post("/schedule", headers=h, json={"service_date": DAY}).status_code == 200
    return north, south, driver, vehicle


def _trip(client, h, **extra):
    # Back at 13:20 (+15 min turnaround: 13:35), the run starts 13:50.
    return client.post(
        "/field-trips",
        headers=h,
        json={
            "requesting_party": "North 4th grade",
            "origin": "North School",
            "destination": "Science museum",
            "departure_at": f"{DAY}T09:00:00",
            "expected_return_at": f"{DAY}T13:20:00",
            "passenger_count": 20,
            "trip_contact": "Ms. Lee",
            **extra,
        },
    ).json()


def _conflicts(client, h, trip, driver, vehicle):
    return client.get(
        f"/field-trips/{trip['id']}/conflicts",
        headers=h,
        params={"driver_id": driver["id"], "vehicle_id": vehicle["id"]},
    ).json()


def test_without_a_known_school_only_the_clock_counts(client, admin_headers):
    _, _, driver, vehicle = _day(client, admin_headers)
    trip = _trip(client, admin_headers)
    assert trip["origin_school_id"] is None
    assert _conflicts(client, admin_headers, trip, driver, vehicle)["routes_needing_cover"] == []


def test_the_drive_back_across_town_makes_the_next_run_need_cover(client, admin_headers):
    north, _, driver, vehicle = _day(client, admin_headers)
    trip = _trip(client, admin_headers, origin_school_id=north["id"])
    assert trip["origin_school_id"] == north["id"]
    [route] = _conflicts(client, admin_headers, trip, driver, vehicle)["routes_needing_cover"]
    assert "South School" in route


def test_an_unknown_origin_school_is_refused(client, admin_headers):
    response = client.post(
        "/field-trips",
        headers=admin_headers,
        json={
            "requesting_party": "x",
            "origin": "x",
            "destination": "y",
            "departure_at": f"{DAY}T09:00:00",
            "expected_return_at": f"{DAY}T10:00:00",
            "trip_contact": "z",
            "origin_school_id": 9999,
        },
    )
    assert response.status_code == 400


@pytest.fixture()
def ors(monkeypatch):
    calls = []

    def fake(api_key, waypoints, vehicle, **kwargs):
        calls.append(waypoints)
        return Directions(
            distance_m=20000.0,
            duration_s=1800.0,
            coordinates=[(w.lat, w.lon) for w in waypoints],
            legs=[Leg(10000.0, 900.0) for _ in waypoints[1:]],
            steps=[
                DirectionStep(f"Head to waypoint {i + 1}", "Main St", 10000.0, 900.0, i)
                for i in range(len(waypoints) - 1)
            ],
        )

    monkeypatch.setattr(schedule.settings, "ors_api_key", "test-key")
    monkeypatch.setattr(schedule, "ors_directions", fake)
    return calls


def test_the_trip_driver_gets_directions_there_and_back(client, admin_headers, db_session, ors):
    h = admin_headers
    north, _, driver, vehicle = _day(client, h)
    museum = client.post(
        "/destination-profiles",
        headers=h,
        json={
            "name": "Science museum",
            "location_lat": 29.75,
            "location_lon": -95.36,
            "approved_entrance": "bus loop on Fannin St",
        },
    ).json()
    trip = _trip(client, h, origin_school_id=north["id"], destination_profile_id=museum["id"])
    client.patch(
        f"/field-trips/{trip['id']}",
        headers=h,
        json={"assigned_driver_id": driver["id"], "assigned_vehicle_id": vehicle["id"]},
    )
    make_user(db_session, email="pat@example.org", role=Role.DRIVER, driver_id=driver["id"])
    pat = auth_headers(login(client, email="pat@example.org"))

    body = client.get(f"/field-trips/{trip['id']}/directions", headers=pat).json()
    assert body["available"] is True
    assert [w["label"] for w in body["waypoints"]] == [
        "North School",
        "Science museum (bus loop on Fannin St)",
        "North School",
    ]
    assert [leg["to_label"] for leg in body["legs"]] == [
        "Science museum (bus loop on Fannin St)",
        "North School",
    ]

    # Another driver can't see it.
    other = client.post(
        "/drivers", headers=h, json={"full_name": "Sam", "license_class": "cdl_a"}
    ).json()
    make_user(db_session, email="sam@example.org", role=Role.DRIVER, driver_id=other["id"])
    sam = auth_headers(login(client, email="sam@example.org"))
    assert client.get(f"/field-trips/{trip['id']}/directions", headers=sam).status_code == 403


def test_without_a_place_on_the_map_the_driver_is_told_why(client, admin_headers, ors):
    h = admin_headers
    north, _, _, _ = _day(client, h)
    trip = _trip(client, h, origin_school_id=north["id"])
    body = client.get(f"/field-trips/{trip['id']}/directions", headers=h).json()
    assert body["available"] is False
    assert "destination placed on the map" in body["reason"]
    assert ors == []
