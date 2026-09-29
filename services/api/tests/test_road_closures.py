"""Road closures and dynamic rerouting (spec section 10). The district
clock is pinned to 07:00 on DAY in America/Chicago (UTC-5 in October)."""

from datetime import UTC, datetime, timedelta

import pytest
from isd_solver import Directions, DirectionStep, Leg

from isd_api.models import AuditLogEntry, Role
from isd_api.routers import schedule
from tests.conftest import auth_headers, login, make_user
from tests.test_route_stops import _crew, _set_stops, _stop, _student

DAY = "2026-10-05"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)  # 07:00 district time


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr("isd_api.ridership_rules.utc_now", lambda: NOW)
    schedule._directions_cache.clear()


def _setup(client, h, db_session):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    far = _stop(client, h, "Far", 29.74)
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
    _set_stops(client, h, route, (far, 0), (near, 10))
    _student(client, h, school, "Ana", far)
    _student(client, h, school, "Cy", near)
    driver, driver_headers = _crew(client, h, "A", db_session)
    client.post(f"/schedule/{DAY}/generate-from-templates", headers=h)
    [assignment] = client.post("/schedule", headers=h, json={"service_date": DAY}).json()[
        "assignments"
    ]
    return assignment, driver_headers


def _close(client, h, lat, lon=-95.40, **fields):
    body = {
        "kind": "collision",
        "note": "Two-car crash, lanes blocked",
        "location_lat": lat,
        "location_lon": lon,
        "radius_m": 150,
        **fields,
    }
    return client.post("/road-closures", headers=h, json=body)


def _alerts(client, h):
    return client.get("/alerts", headers=h, params={"service_date": DAY}).json()["alerts"]


# --- Recording closures --------------------------------------------------


def test_dispatch_records_a_closure_and_it_is_audited(client, admin_headers, db_session):
    make_user(db_session, email="d@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="d@example.org"))
    response = _close(client, dispatcher, 29.725)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["active"] is True and body["cleared"] is False
    assert body["starts_at"].startswith("2026-10-05T12:00")  # now
    [entry] = (
        db_session.query(AuditLogEntry).filter(AuditLogEntry.entity_type == "road_closure").all()
    )
    assert entry.action == "created" and entry.after_state["kind"] == "collision"


def test_drivers_cannot_record_closures(client, admin_headers, db_session):
    _, driver = _crew(client, admin_headers, "A", db_session)
    assert _close(client, driver, 29.725).status_code == 403
    assert client.get("/road-closures", headers=driver).status_code == 403


def test_times_are_checked_and_ended_or_cleared_closures_drop_off_the_list(client, admin_headers):
    later = (NOW + timedelta(hours=1)).isoformat()
    earlier = (NOW - timedelta(hours=1)).isoformat()
    bad = _close(client, admin_headers, 29.725, starts_at=later, ends_at=earlier)
    assert bad.status_code == 400
    ended = _close(
        client,
        admin_headers,
        29.725,
        starts_at=(NOW - timedelta(hours=3)).isoformat(),
        ends_at=earlier,
    ).json()
    upcoming = _close(client, admin_headers, 29.73, starts_at=later).json()
    live = _close(client, admin_headers, 29.72).json()

    listed = {c["id"]: c for c in client.get("/road-closures", headers=admin_headers).json()}
    assert set(listed) == {upcoming["id"], live["id"]}
    assert (listed[live["id"]]["active"], listed[upcoming["id"]]["active"]) == (True, False)

    cleared = client.post(f"/road-closures/{live['id']}/clear", headers=admin_headers)
    assert cleared.json()["cleared"] is True and cleared.json()["active"] is False
    assert (
        client.post(f"/road-closures/{live['id']}/clear", headers=admin_headers).status_code == 409
    )
    assert (
        client.patch(f"/road-closures/{live['id']}", headers=admin_headers, json={"note": "x"})
    ).status_code == 409
    everything = client.get(
        "/road-closures", headers=admin_headers, params={"include_ended": True}
    ).json()
    assert {c["id"] for c in everything} == {ended["id"], upcoming["id"], live["id"]}


def test_a_closure_can_be_given_an_end_or_made_open_ended(client, admin_headers):
    closure = _close(client, admin_headers, 29.725).json()
    end = (NOW + timedelta(hours=2)).isoformat()
    ended = client.patch(
        f"/road-closures/{closure['id']}",
        headers=admin_headers,
        json={"ends_at": end, "radius_m": 300},
    ).json()
    assert ended["ends_at"].startswith("2026-10-05T14:00") and ended["radius_m"] == 300
    reopened = client.patch(
        f"/road-closures/{closure['id']}", headers=admin_headers, json={"ends_at": None}
    ).json()
    assert reopened["ends_at"] is None


# --- Which runs it affects ------------------------------------------------


def test_a_closure_on_the_way_is_flagged_and_one_at_a_stop_is_critical(
    client, admin_headers, db_session
):
    assignment, driver = _setup(client, admin_headers, db_session)
    on_the_way = _close(client, admin_headers, 29.725).json()  # between Far and Near
    assert [r["assignment_id"] for r in on_the_way["affected_runs"]] == [assignment["id"]]
    assert on_the_way["affected_runs"][0]["stop_inside"] is None
    kinds = [(a["kind"], a["severity"]) for a in _alerts(client, admin_headers)]
    assert ("road_closure", "warning") in kinds

    at_stop = _close(client, admin_headers, 29.71, kind="flooding", note="Underpass flooded").json()
    assert at_stop["affected_runs"][0]["stop_inside"] == "Near"
    critical = [a for a in _alerts(client, admin_headers) if a["kind"] == "closure_at_stop"]
    assert critical[0]["severity"] == "critical"
    assert "Near stop" in critical[0]["message"] and "flooding" in critical[0]["message"]

    [mine] = client.get(f"/schedule/{DAY}/my-assignments", headers=driver).json()
    assert mine["closure_notes"] == [
        "collision: Two-car crash, lanes blocked",
        "flooding: Underpass flooded (the Near stop is inside it)",
    ]


def test_a_closure_elsewhere_or_cleared_affects_nothing(client, admin_headers, db_session):
    assignment, driver = _setup(client, admin_headers, db_session)
    far_away = _close(client, admin_headers, 29.72, lon=-95.30).json()  # about 6 mi east
    assert far_away["affected_runs"] == []
    near = _close(client, admin_headers, 29.725).json()
    client.post(f"/road-closures/{near['id']}/clear", headers=admin_headers)
    assert not [
        a for a in _alerts(client, admin_headers) if a["kind"].startswith(("road", "closure"))
    ]
    [mine] = client.get(f"/schedule/{DAY}/my-assignments", headers=driver).json()
    assert mine["closure_notes"] == []


# --- Rerouting -----------------------------------------------------------


def test_directions_route_around_closures_in_force(client, admin_headers, db_session, monkeypatch):
    calls = []

    def fake(api_key, waypoints, vehicle, **kwargs):
        calls.append(kwargs)
        return Directions(
            1000.0,
            120.0,
            [(w.lat, w.lon) for w in waypoints],
            [Leg(500.0, 60.0)] * 2,
            [DirectionStep("Go", "", 1000.0, 120.0, 0)],
        )

    monkeypatch.setattr(schedule.settings, "ors_api_key", "test-key")
    monkeypatch.setattr(schedule, "ors_directions", fake)
    assignment, driver = _setup(client, admin_headers, db_session)
    url = f"/schedule/assignments/{assignment['id']}/directions"

    client.get(url, headers=driver)
    assert calls[-1]["avoid_areas"] == []
    closure = _close(client, admin_headers, 29.725, radius_m=400).json()
    client.get(url, headers=driver)  # a new closure: not served from the cache
    [(centre, radius)] = calls[-1]["avoid_areas"]
    assert (centre.lat, centre.lon, radius) == (29.725, -95.40, 400.0)
    client.post(f"/road-closures/{closure['id']}/clear", headers=admin_headers)
    # Cleared: the same closures as the first request, whose closure-free
    # directions are still cached, so no new ORS call.
    assert client.get(url, headers=driver).status_code == 200
    assert len(calls) == 2


def test_the_scheduler_avoids_closures_on_the_day_it_plans(
    client, admin_headers, db_session, monkeypatch
):
    seen = []

    def fake_estimator(**kwargs):
        seen.append(kwargs["avoid_polygons"])
        return lambda a, b, vehicle: 10

    monkeypatch.setattr(schedule.settings, "ors_api_key", "test-key")
    monkeypatch.setattr(schedule, "ors_deadhead_estimator", fake_estimator)
    _setup(client, admin_headers, db_session)
    # In force on DAY (it started late the evening before, district time).
    _close(
        client,
        admin_headers,
        29.725,
        starts_at=(NOW - timedelta(hours=8)).isoformat(),
        ends_at=(NOW - timedelta(hours=6)).isoformat(),
    )
    # Ended the day before: not relevant.
    _close(
        client,
        admin_headers,
        29.73,
        starts_at=(NOW - timedelta(days=2)).isoformat(),
        ends_at=(NOW - timedelta(days=1, hours=12)).isoformat(),
    )
    seen.clear()
    client.post("/schedule", headers=admin_headers, json={"service_date": DAY})
    polygons = seen[-1]
    assert polygons["type"] == "MultiPolygon" and len(polygons["coordinates"]) == 1
