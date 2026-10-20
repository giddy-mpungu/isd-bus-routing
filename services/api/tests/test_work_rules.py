"""District driver work-hour rules (spec section 2.1): off until the
district sets them (product owner, 2026-10-19), then enforced by the
solver, manual reassignment, and field-trip assignment."""

from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user

DAY = "2026-08-03"
NEXT_DAY = "2026-08-04"

BASE = {"crews_used_weight": 1, "deadhead_minutes_weight": 0, "arrival_buffer_weight": 0}


def _rules(client, h, **rules):
    response = client.put("/optimization-settings", headers=h, json={**BASE, **rules})
    assert response.status_code == 200, response.text
    return response.json()


def _school(client, h, name="Riverside"):
    return client.post(
        "/schools", headers=h, json={"name": name, "location_lat": 29.7, "location_lon": -95.4}
    ).json()


def _driver(client, h, name):
    return client.post(
        "/drivers", headers=h, json={"full_name": name, "license_class": "cdl_a"}
    ).json()


def _crew(client, h, driver, day=DAY, label=None):
    vehicle = client.post(
        "/vehicles",
        headers=h,
        json={"label": label or f"Bus for {driver['full_name']} {day}", "nominal_capacity": 40},
    ).json()
    return client.post(
        "/crews",
        headers=h,
        json={
            "service_date": day,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 300,
            "available_window_latest": 1200,
        },
    ).json()


def _run(client, h, school, start, end, day=DAY):
    return client.post(
        "/runs",
        headers=h,
        json={
            "service_date": day,
            "school_id": school["id"],
            "direction": "am" if start < 720 else "pm",
            "window_earliest": start,
            "window_latest": end,
            "duration_minutes": end - start,
        },
    ).json()


def _solve(client, h, day=DAY):
    return client.post("/schedule", headers=h, json={"service_date": day})


def test_rules_are_off_until_the_district_sets_them(client, admin_headers):
    settings = client.get("/optimization-settings", headers=admin_headers).json()
    for name in ("max_duty_minutes", "break_after_minutes", "break_minutes", "min_rest_minutes"):
        assert settings[name] is None
    saved = _rules(client, admin_headers, max_duty_minutes=600, min_rest_minutes=600)
    assert (saved["max_duty_minutes"], saved["min_rest_minutes"]) == (600, 600)
    assert _rules(client, admin_headers)["max_duty_minutes"] is None


def test_a_break_needs_both_its_numbers(client, admin_headers):
    response = client.put(
        "/optimization-settings", headers=admin_headers, json={**BASE, "break_after_minutes": 240}
    )
    assert response.status_code == 422


def test_only_transportation_admins_set_the_rules(client, db_session):
    make_user(db_session, email="dana@example.org", role=Role.DISPATCHER)
    dana = auth_headers(login(client, email="dana@example.org"))
    response = client.put(
        "/optimization-settings", headers=dana, json={**BASE, "max_duty_minutes": 600}
    )
    assert response.status_code == 403


def test_a_daily_duty_limit_gives_a_long_day_to_two_drivers(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    _crew(client, h, _driver(client, h, "Pat"))
    _crew(client, h, _driver(client, h, "Sam"))
    _run(client, h, school, 360, 420)  # 06:00-07:00
    _run(client, h, school, 900, 960)  # 15:00-16:00, ten hours after the start
    one = _solve(client, h).json()
    assert len({a["crew_id"] for a in one["assignments"]}) == 1

    _rules(client, h, max_duty_minutes=480)
    two = _solve(client, h).json()
    assert len({a["crew_id"] for a in two["assignments"]}) == 2
    assert "continuous-duty limit (480 min)" in two["assignments"][0]["explanation_text"]


def test_rest_between_days_keeps_a_late_driver_off_the_early_run(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    pat, sam = _driver(client, h, "Pat"), _driver(client, h, "Sam")
    # Pat works until 20:00 on the first day.
    late = _run(client, h, school, 1140, 1200)
    first_crew = _crew(client, h, pat)
    assert _solve(client, h).json()["assignments"][0]["crew_id"] == first_crew["id"]

    _rules(client, h, min_rest_minutes=12 * 60)
    _run(client, h, school, 360, 420, day=NEXT_DAY)  # 06:00 next morning: only 10 hours later
    _crew(client, h, pat, day=NEXT_DAY)
    sam_crew = _crew(client, h, sam, day=NEXT_DAY)
    [early] = _solve(client, h, NEXT_DAY).json()["assignments"]
    assert early["crew_id"] == sam_crew["id"]
    assert late["id"] != early["run_id"]


def test_moving_a_run_by_hand_onto_a_driver_without_a_break_is_refused(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    pat_crew = _crew(client, h, _driver(client, h, "Pat"))
    sam_crew = _crew(client, h, _driver(client, h, "Sam"))
    _run(client, h, school, 360, 480)  # 06:00-08:00
    _run(client, h, school, 490, 610)  # 08:10-10:10
    _rules(client, h, break_after_minutes=180, break_minutes=30)
    assignments = _solve(client, h).json()["assignments"]
    assert len({a["crew_id"] for a in assignments}) == 2
    on_sam = next(a for a in assignments if a["crew_id"] == sam_crew["id"])
    other = next(a for a in assignments if a["crew_id"] == pat_crew["id"])

    response = client.patch(
        f"/schedule/assignments/{on_sam['id']}", headers=h, json={"crew_id": other["crew_id"]}
    )
    assert response.status_code == 422
    assert "without a 30-minute break; the district allows 180" in response.json()["detail"]


def _trip(client, h, depart="2026-08-03T09:00:00", back="2026-08-03T13:30:00"):
    return client.post(
        "/field-trips",
        headers=h,
        json={
            "requesting_party": "Riverside 4th grade",
            "origin": "Riverside",
            "destination": "Science museum",
            "departure_at": depart,
            "expected_return_at": back,
            "passenger_count": 20,
            "trip_contact": "Ms. Lee",
        },
    ).json()


def test_a_field_trip_that_would_make_the_day_too_long_is_refused(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    pat = _driver(client, h, "Pat")
    crew = _crew(client, h, pat)
    _run(client, h, school, 360, 420)  # 06:00-07:00
    _solve(client, h)
    _rules(client, h, max_duty_minutes=8 * 60)
    trip = _trip(client, h)  # 09:00-13:30 (+15 min turnaround): 06:00-13:45 is fine
    conflicts = client.get(
        f"/field-trips/{trip['id']}/conflicts",
        headers=h,
        params={"driver_id": pat["id"], "vehicle_id": crew["vehicle_id"]},
    ).json()
    assert not any("on duty" in c for c in conflicts["conflicts"])

    late = _trip(client, h, back="2026-08-03T15:30:00")  # until 15:45: 585 minutes
    conflicts = client.get(
        f"/field-trips/{late['id']}/conflicts",
        headers=h,
        params={"driver_id": pat["id"], "vehicle_id": crew["vehicle_id"]},
    ).json()
    assert any(
        "on duty 585 minutes (06:00-15:45), over the limit of 480" in c
        for c in conflicts["conflicts"]
    ), conflicts


def test_route_planning_uses_the_ride_time_weight(client, admin_headers, monkeypatch):
    from isd_solver import RoutePlan

    from isd_api.routers import templates

    seen = {}

    def fake_plan(school, stops, *, direction, ride_time_weight=0, **_):
        seen["weight"] = ride_time_weight
        return RoutePlan(stops=[], total_minutes=0, ride_limits_met=True)

    monkeypatch.setattr(templates, "plan_route", fake_plan)
    h = admin_headers
    school = _school(client, h)
    stop = client.post(
        "/stops", headers=h, json={"label": "Oak", "location_lat": 29.71, "location_lon": -95.4}
    ).json()
    route = client.post(
        "/route-templates",
        headers=h,
        json={
            "school_id": school["id"],
            "direction": "pm",
            "window_earliest": 900,
            "window_latest": 960,
            "duration_minutes": 30,
            "days_of_week": [0, 1, 2, 3, 4],
        },
    ).json()
    client.put(
        f"/route-templates/{route['id']}/stops",
        headers=h,
        json={"stops": [{"stop_id": stop["id"], "minutes_from_start": 10}]},
    )
    assert _rules(client, h, ride_time_weight=2)["ride_time_weight"] == 2
    response = client.post(f"/route-templates/{route['id']}/stops/plan", headers=h, json={})
    assert response.status_code == 200, response.text
    assert seen["weight"] == 2
