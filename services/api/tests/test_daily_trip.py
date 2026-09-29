"""A run's trip on the day (spec section 4.3): empty stops skipped, arrival
times recalculated, families told when their stop's time moves."""

from isd_api.daily_trip import MATERIAL_CHANGE_MINUTES
from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user
from tests.test_route_stops import _crew, _set_stops, _stop, _student

DAY = "2026-10-05"  # a Monday


def _setup(client, h, db_session, direction="am"):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    # Far and Near sit on a line north of school; Mid is a detour east of
    # it, still best visited between them, so skipping it saves real time.
    far = _stop(client, h, "Far", 29.75)
    mid = client.post(
        "/stops", headers=h, json={"label": "Mid", "location_lat": 29.73, "location_lon": -95.37}
    ).json()
    near = _stop(client, h, "Near", 29.71)
    window = (420, 500) if direction == "am" else (900, 980)
    route = client.post(
        "/route-templates",
        headers=h,
        json={
            "school_id": school["id"],
            "direction": direction,
            "window_earliest": window[0],
            "window_latest": window[1],
            "duration_minutes": 40,
            "days_of_week": [0, 1, 2, 3, 4],
        },
    ).json()
    _set_stops(client, h, route, (far, None), (mid, None), (near, None))
    students = {
        "Ana": _student(client, h, school, "Ana", far),
        "Ben": _student(client, h, school, "Ben", mid),
        "Cy": _student(client, h, school, "Cy", near),
    }
    planned = client.post(
        f"/route-templates/{route['id']}/stops/plan", headers=h, json={"apply": True}
    )
    assert planned.status_code == 200, planned.text
    _, driver = _crew(client, h, "A", db_session)
    client.post(f"/schedule/{DAY}/generate-from-templates", headers=h)
    solved = client.post("/schedule", headers=h, json={"service_date": DAY})
    assert solved.status_code == 200, solved.text
    return {"students": students, "driver": driver, "plan": planned.json()}


def _not_riding(client, h, student, direction="am"):
    response = client.patch(
        f"/students/{student['id']}/ridership",
        headers=h,
        json={"service_date": DAY, "direction": direction, "is_riding": False},
    )
    assert response.status_code == 204, response.text


def _roster(client, day):
    [mine] = client.get(f"/schedule/{DAY}/my-assignments", headers=day["driver"]).json()
    return {s["stop_label"]: s for s in mine["stops"]}


def test_with_everyone_riding_todays_times_match_the_plan(client, admin_headers, db_session):
    day = _setup(client, admin_headers, db_session)
    stops = _roster(client, day)
    assert [s["stop_label"] for s in day["plan"]["stops"]] == ["Far", "Mid", "Near"]
    for label in ("Far", "Mid", "Near"):
        s = stops[label]
        assert s["skipped"] is False
        assert abs(s["eta_minute"] - s["planned_minute"]) <= 1, s


def test_an_empty_stop_is_skipped_and_earlier_pickups_move_later_never_earlier(
    client, admin_headers, db_session
):
    day = _setup(client, admin_headers, db_session)
    before = _roster(client, day)
    _not_riding(client, admin_headers, day["students"]["Ben"])
    after = _roster(client, day)

    assert after["Mid"]["skipped"] is True
    assert after["Mid"]["eta_minute"] is None and after["Mid"]["student_names"] == []
    # Far is before the skipped detour: its pickup moves later (the bus
    # still reaches school at the planned time); Near, after it, doesn't move.
    assert after["Far"]["eta_minute"] > before["Far"]["eta_minute"]
    assert after["Near"]["eta_minute"] == before["Near"]["eta_minute"]
    for label in ("Far", "Near"):
        assert after[label]["eta_minute"] >= after[label]["planned_minute"] - 1


def test_an_afternoon_trip_brings_later_drop_offs_forward(client, admin_headers, db_session):
    day = _setup(client, admin_headers, db_session, direction="pm")
    assert [s["stop_label"] for s in day["plan"]["stops"]] == ["Near", "Mid", "Far"]
    before = _roster(client, day)
    _not_riding(client, admin_headers, day["students"]["Ben"], direction="pm")
    after = _roster(client, day)
    assert after["Mid"]["skipped"] is True
    assert after["Near"]["eta_minute"] == before["Near"]["eta_minute"]
    assert after["Far"]["eta_minute"] < before["Far"]["eta_minute"]


def test_a_day_with_nobody_riding_skips_every_stop(client, admin_headers, db_session):
    day = _setup(client, admin_headers, db_session)
    for student in day["students"].values():
        _not_riding(client, admin_headers, student)
    assert all(s["skipped"] for s in _roster(client, day).values())


def test_a_family_sees_todays_time_at_their_stop_and_whether_it_moved(
    client, admin_headers, db_session
):
    day = _setup(client, admin_headers, db_session)
    parent = make_user(db_session, email="parent@example.org", role=Role.PARENT)
    client.post(
        f"/students/{day['students']['Ana']['id']}/guardians",
        headers=admin_headers,
        json={"user_id": parent.id},
    )
    family = auth_headers(login(client, email="parent@example.org"))

    def ana():
        [member] = client.get(
            "/students/my-family", headers=family, params={"service_date": DAY}
        ).json()
        return member

    usual = ana()["am_eta"]
    assert usual["stop_label"] == "Far"
    assert usual["changed"] is False
    assert abs(usual["eta_minute"] - usual["planned_minute"]) <= 1
    # Ben rides the afternoon only: nothing planned for his family's PM here.
    assert ana()["pm_eta"] is None  # no PM route

    _not_riding(client, admin_headers, day["students"]["Ben"])
    moved = ana()["am_eta"]
    assert moved["eta_minute"] - moved["planned_minute"] >= MATERIAL_CHANGE_MINUTES
    assert moved["changed"] is True

    # Not riding today: no time to show.
    _not_riding(client, admin_headers, day["students"]["Ana"])
    assert ana()["am_eta"] is None
