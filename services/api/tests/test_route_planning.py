"""Planning a route's stop order and times (spec sections 2, 3.1, 16) with
isd_solver.routing: POST /route-templates/{id}/stops/plan."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user
from tests.test_route_stops import _route, _school, _set_stops, _stop, _student

DAY = "2026-10-05"


def _plan(client, h, route, apply=False):
    return client.post(
        f"/route-templates/{route['id']}/stops/plan", headers=h, json={"apply": apply}
    )


def _line_of_stops(client, h):
    school = _school(client, h)  # at 29.70
    near = _stop(client, h, "Near", 29.71)
    mid = _stop(client, h, "Mid", 29.72)
    far = _stop(client, h, "Far", 29.73)
    return school, near, mid, far


def test_a_morning_plan_runs_far_to_near_and_saves_nothing_until_applied(client, admin_headers):
    school, near, mid, far = _line_of_stops(client, admin_headers)
    route = _route(client, admin_headers, school, duration=40)
    _set_stops(client, admin_headers, route, (near, None), (far, None), (mid, None))

    response = _plan(client, admin_headers, route)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [s["stop_label"] for s in body["stops"]] == ["Far", "Mid", "Near"]
    minutes = [s["minutes_from_start"] for s in body["stops"]]
    assert minutes[0] == 0 and minutes == sorted(minutes)
    assert body["total_minutes"] > minutes[-1]
    assert body["current_duration_minutes"] == 40
    assert body["applied"] is False and body["ride_limits_met"] is True
    assert "not road-network travel times" in body["travel_estimate"]

    saved = client.get(f"/route-templates/{route['id']}/stops", headers=admin_headers).json()
    assert [s["stop_label"] for s in saved] == ["Near", "Far", "Mid"]


def test_applying_saves_the_order_times_and_duration(client, admin_headers, db_session):
    school, near, mid, far = _line_of_stops(client, admin_headers)
    route = _route(client, admin_headers, school, duration=40)
    _set_stops(client, admin_headers, route, (near, None), (far, None), (mid, None))

    body = _plan(client, admin_headers, route, apply=True).json()
    assert body["applied"] is True
    saved = client.get(f"/route-templates/{route['id']}/stops", headers=admin_headers).json()
    assert [(s["stop_label"], s["minutes_from_start"]) for s in saved] == [
        (s["stop_label"], s["minutes_from_start"]) for s in body["stops"]
    ]
    [template] = client.get("/route-templates", headers=admin_headers).json()
    assert template["duration_minutes"] == body["total_minutes"]

    # Days generated from now on use the planned duration.
    client.post(f"/schedule/{DAY}/generate-from-templates", headers=admin_headers)
    [run] = client.get("/runs", headers=admin_headers, params={"service_date": DAY}).json()
    assert run["duration_minutes"] == body["total_minutes"]

    [entry] = db_session.query(AuditLogEntry).filter(AuditLogEntry.action == "stops_planned").all()
    assert entry.before_state["duration_minutes"] == 40
    assert entry.after_state["duration_minutes"] == body["total_minutes"]


def test_an_afternoon_plan_starts_at_school_and_drops_near_first(client, admin_headers):
    school, near, mid, far = _line_of_stops(client, admin_headers)
    route = client.post(
        "/route-templates",
        headers=admin_headers,
        json={
            "school_id": school["id"],
            "direction": "pm",
            "window_earliest": 900,
            "window_latest": 960,
            "duration_minutes": 40,
            "days_of_week": [0, 1, 2, 3, 4],
        },
    ).json()
    _set_stops(client, admin_headers, route, (far, None), (near, None), (mid, None))
    body = _plan(client, admin_headers, route).json()
    assert [s["stop_label"] for s in body["stops"]] == ["Near", "Mid", "Far"]
    assert body["stops"][0]["minutes_from_start"] > 0  # driving from school first


def test_students_at_a_stop_set_its_ride_limit_and_loading_time(client, admin_headers):
    school, near, _, far = _line_of_stops(client, admin_headers)
    route = _route(client, admin_headers, school)
    _set_stops(client, admin_headers, route, (near, None), (far, None))
    before = _plan(client, admin_headers, route).json()
    assert all(s["ride_limit_minutes"] is None and s["riders"] == 0 for s in before["stops"])

    client.post(
        "/qualifications",
        headers=admin_headers,
        json={"code": "wheelchair_lift", "kind": "vehicle_capability"},
    )
    for name, grade in (("Ana", "3"), ("Ben", "10")):
        student = _student(client, admin_headers, school, name, far)
        client.patch(f"/students/{student['id']}", headers=admin_headers, json={"grade": grade})
    lift = _student(client, admin_headers, school, "Cy", far)
    client.patch(
        f"/students/{lift['id']}",
        headers=admin_headers,
        json={"accommodation_codes": ["wheelchair_lift"]},
    )
    after = _plan(client, admin_headers, route).json()
    far_stop = next(s for s in after["stops"] if s["stop_label"] == "Far")
    # Ana is elementary (45 min), Ben high school (60), Cy has no grade (strictest, 45).
    assert (far_stop["riders"], far_stop["ride_limit_minutes"]) == (3, 45)
    # Three riders, one using the lift: more time at the stop.
    assert after["total_minutes"] > before["total_minutes"]


def test_a_ride_limit_that_cannot_be_met_is_reported_by_stop(client, admin_headers):
    school = _school(client, admin_headers)
    remote = _stop(client, admin_headers, "Remote", 29.70 + 0.3)  # about 21 mi of road
    route = _route(client, admin_headers, school, duration=40)
    _set_stops(client, admin_headers, route, (remote, None))
    student = _student(client, admin_headers, school, "Ana", remote)
    client.patch(f"/students/{student['id']}", headers=admin_headers, json={"grade": "2"})
    body = _plan(client, admin_headers, route).json()
    assert body["ride_limits_met"] is False
    [violation] = body["violations"]
    assert violation.startswith("Remote: ") and violation.endswith("(limit 45 min)")


def test_planning_needs_stops_and_the_right_role(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    route = _route(client, admin_headers, school)
    empty = _plan(client, admin_headers, route)
    assert empty.status_code == 400 and "Add stops" in empty.json()["detail"]

    make_user(db_session, email="d@example.org", role=Role.DISPATCHER)
    make_user(db_session, email="s@example.org", role=Role.SCHOOL_ADMIN)
    oak = _stop(client, admin_headers, "Oak", 29.71)
    _set_stops(client, admin_headers, route, (oak, None))
    dispatcher = auth_headers(login(client, email="d@example.org"))
    school_admin = auth_headers(login(client, email="s@example.org"))
    assert _plan(client, dispatcher, route).status_code == 200
    assert _plan(client, school_admin, route).status_code == 403


def test_a_plan_longer_than_the_routes_window_is_shown_but_not_applied(client, admin_headers):
    school = _school(client, admin_headers)
    remote = _stop(client, admin_headers, "Remote", 29.70 + 0.3)
    route = _route(client, admin_headers, school, duration=40)  # a 60-minute window
    _set_stops(client, admin_headers, route, (remote, None))
    shown = _plan(client, admin_headers, route).json()
    assert shown["window_minutes"] == 60
    assert shown["total_minutes"] > 60 and shown["fits_window"] is False
    refused = _plan(client, admin_headers, route, apply=True)
    assert refused.status_code == 409
    assert "Widen the window or split the route" in refused.json()["detail"]
    [template] = client.get("/route-templates", headers=admin_headers).json()
    assert template["duration_minutes"] == 40
