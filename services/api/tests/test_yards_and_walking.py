"""Depth from the October review, part 3 (spec section 2.2): each bus's
yard counts in the fleet's empty driving, and a walking weight trades
shorter walks against fewer stops."""

import pytest

from isd_api.stop_proposals import propose
from tests.test_stop_proposals import _generate, _school, _student_at, at, home

SERVICE_DATE = "2026-09-01"


def _vehicle(client, h, label, **fields):
    return client.post("/vehicles", headers=h, json={"label": label, **fields})


def test_a_vehicle_keeps_where_it_parks(client, admin_headers):
    h = admin_headers
    bus = _vehicle(client, h, "Bus 7", yard_lat=29.75, yard_lon=-95.45).json()
    assert (bus["yard_lat"], bus["yard_lon"]) == (29.75, -95.45)
    assert _vehicle(client, h, "Bus 8", yard_lat=29.75).status_code == 422

    half = client.patch(f"/vehicles/{bus['id']}", headers=h, json={"yard_lon": -95.5})
    assert half.status_code == 422
    cleared = client.patch(
        f"/vehicles/{bus['id']}", headers=h, json={"yard_lat": None, "yard_lon": None}
    ).json()
    assert (cleared["yard_lat"], cleared["yard_lon"]) == (None, None)


def _weights(client, h, **extra):
    response = client.put(
        "/optimization-settings",
        headers=h,
        json={"crews_used_weight": 1, "deadhead_minutes_weight": 1, "arrival_buffer_weight": 0}
        | extra,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_bus_parked_by_the_school_gets_its_run(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    client.post(
        "/runs",
        headers=h,
        json={
            "service_date": SERVICE_DATE,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 420,
            "window_latest": 480,
            "duration_minutes": 40,
            "buffer_minutes": 0,
        },
    )
    crews = {}
    # Listed first, so it would win a tie.
    for label, lat in (("Far", 29.90), ("Near", 29.70)):
        driver = client.post(
            "/drivers", headers=h, json={"license_class": "cdl_a", "full_name": f"Driver {label}"}
        ).json()
        vehicle = _vehicle(client, h, label, yard_lat=lat, yard_lon=-95.4).json()
        crew = client.post(
            "/crews",
            headers=h,
            json={
                "service_date": SERVICE_DATE,
                "driver_id": driver["id"],
                "vehicle_id": vehicle["id"],
                "available_window_earliest": 0,
                "available_window_latest": 1439,
            },
        ).json()
        crews[crew["id"]] = label
    _weights(client, h)

    result = client.post("/schedule", headers=h, json={"service_date": SERVICE_DATE}).json()
    [assignment] = result["assignments"]
    assert crews[assignment["crew_id"]] == "Near"
    assert result["total_yard_minutes"] == 0


def test_the_stop_goes_where_the_walks_add_up_to_least():
    # Two children at one house, one a little east: the stop is at the
    # house (0.15 mi walked in all), not between them (0.2 mi).
    [stop] = propose([home(1), home(2), home(3, east_mi=0.15)], [], min_spacing_miles=0.1)
    assert (stop.lat, stop.lon) == pytest.approx(at(), abs=1e-5)


def test_the_walking_weight_trades_shorter_walks_for_more_stops(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    # Elementary children walk up to 0.25 mi; these two live 0.19 mi apart.
    _student_at(client, h, school, "Ana")
    _student_at(client, h, school, "Ben", east_mi=0.19)

    assert len(_generate(client, h, school).json()["proposals"]) == 1
    assert _weights(client, h, walking_weight=10)["walking_weight"] == 10
    # Now each may walk 0.125 mi: one stop each.
    assert len(_generate(client, h, school).json()["proposals"]) == 2
