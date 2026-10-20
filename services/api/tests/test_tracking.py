"""Live tracking (spec section 9 "direction of travel", "route deviation"):
which way a bus is heading, and an alert when it's well away from its
route while a run is under way."""

from datetime import UTC, datetime, timedelta

import pytest

from isd_api import tracking
from tests.test_directions import DAY, _setup

# 07:30 in the district (America/Chicago, UTC-5 in October) on DAY, when
# the morning run (07:00-08:20 window) is under way.
NOW = datetime(2026, 10, 5, 12, 30, tzinfo=UTC)


@pytest.fixture()
def clock(monkeypatch):
    monkeypatch.setattr("isd_api.ridership_rules.utc_now", lambda: NOW)


def test_compass_points():
    assert [tracking.compass(d) for d in (0, 44, 46, 90, 180, 270, 359)] == [
        "N",
        "NE",
        "NE",
        "E",
        "S",
        "W",
        "N",
    ]
    assert round(tracking.bearing((29.70, -95.40), (29.71, -95.40))) == 0
    assert round(tracking.bearing((29.70, -95.40), (29.70, -95.39))) == 90


def test_distance_from_a_route_is_to_its_nearest_leg():
    line = [(29.74, -95.40), (29.71, -95.40), (29.70, -95.40)]
    assert tracking.distance_from_line((29.72, -95.40), line) < 1
    # About 0.01 degrees of longitude west of the line: roughly 970 m.
    assert 900 < tracking.distance_from_line((29.72, -95.41), line) < 1000
    # Past the end of the line, it's the distance to the end.
    assert 1050 < tracking.distance_from_line((29.75, -95.40), line) < 1150


def _under_way(client, admin_headers, db_session):
    assignment, driver_headers = _setup(client, admin_headers, db_session)
    for step in ("acknowledged", "en_route"):
        response = client.patch(
            f"/schedule/assignments/{assignment['id']}/status",
            headers=driver_headers,
            json={"status": step},
        )
        assert response.status_code == 200, response.text
    driver_id = client.get("/users/me", headers=driver_headers).json()["driver_id"]
    return assignment, driver_headers, driver_id


def _report(client, headers, driver_id, lat, lon, minutes_ago):
    response = client.put(
        f"/drivers/{driver_id}/position",
        headers=headers,
        json={
            "service_date": DAY,
            "location_lat": lat,
            "location_lon": lon,
            "recorded_at": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
        },
    )
    assert response.status_code == 204, response.text


def _off_route(client, h):
    alerts = client.get("/alerts", headers=h, params={"service_date": DAY}).json()["alerts"]
    return [a for a in alerts if a["kind"] == "off_route"]


def test_a_bus_on_its_route_raises_nothing(client, admin_headers, db_session, clock):
    _, driver, driver_id = _under_way(client, admin_headers, db_session)
    _report(client, driver, driver_id, 29.735, -95.401, 2)
    _report(client, driver, driver_id, 29.73, -95.401, 1)
    assert _off_route(client, admin_headers) == []


def test_a_bus_far_from_its_route_is_flagged_with_its_heading(
    client, admin_headers, db_session, clock
):
    assignment, driver, driver_id = _under_way(client, admin_headers, db_session)
    # Heading west, away from the stops along -95.40.
    _report(client, driver, driver_id, 29.73, -95.44, 2)
    _report(client, driver, driver_id, 29.73, -95.45, 1)
    [alert] = _off_route(client, admin_headers)
    assert alert["severity"] == "warning"
    assert alert["entity_id"] == assignment["id"]
    assert "4.8 km from its route" in alert["message"]
    assert alert["message"].endswith("heading W")

    [bus] = client.get(f"/schedule/{DAY}/fleet-positions", headers=admin_headers).json()
    assert (bus["heading"], bus["heading_degrees"]) == ("W", 270)


def test_a_bus_standing_still_has_no_heading(client, admin_headers, db_session, clock):
    _, driver, driver_id = _under_way(client, admin_headers, db_session)
    _report(client, driver, driver_id, 29.73, -95.401, 2)
    _report(client, driver, driver_id, 29.73001, -95.401, 1)  # a metre: GPS jitter
    [bus] = client.get(f"/schedule/{DAY}/fleet-positions", headers=admin_headers).json()
    assert bus["heading"] is None
