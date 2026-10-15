"""School bell schedules, special days and the bus windows they set
(isd_api/bells.py). The ridership clock is pinned to 2026-08-01, so the
September dates below are days still to come."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user

MONDAY = "2026-09-21"
TUESDAY = "2026-09-22"
WEEKDAYS = [0, 1, 2, 3, 4]


def _school(client, h, name="Riverside Elementary"):
    return client.post(
        "/schools", headers=h, json={"name": name, "location_lat": 29.70, "location_lon": -95.40}
    ).json()


def _schedule(client, h, school, name, first, dismissal, **extra):
    return client.post(
        f"/schools/{school['id']}/bell-schedules",
        headers=h,
        json={"name": name, "first_bell_minute": first, "dismissal_minute": dismissal, **extra},
    )


def _route(client, h, school, direction="am", follows_bells=True, **extra):
    return client.post(
        "/route-templates",
        headers=h,
        json={
            "school_id": school["id"],
            "direction": direction,
            "follows_bells": follows_bells,
            "duration_minutes": 40,
            "buffer_minutes": 5,
            "days_of_week": WEEKDAYS,
            **extra,
        },
    )


def _generate(client, h, day):
    return client.post(f"/schedule/{day}/generate-from-templates", headers=h)


def _run_window(client, h, day):
    [run] = client.get("/runs", headers=h, params={"service_date": day}).json()
    return run["window_earliest"], run["window_latest"]


def test_a_morning_route_arrives_in_the_districts_window_before_the_first_bell(
    client, admin_headers
):
    school = _school(client, admin_headers)
    regular = _schedule(client, admin_headers, school, "Regular", 8 * 60, 15 * 60)
    assert regular.status_code == 201, regular.text
    assert regular.json()["is_regular"] is True  # a school's first schedule

    route = _route(client, admin_headers, school)
    assert route.status_code == 201, route.text
    # Bell 08:00, arrive 10-25 min before: the run ends between 07:35 and
    # 07:50, so with 45 minutes of driving and buffer it can start at 06:50.
    assert (route.json()["window_earliest"], route.json()["window_latest"]) == (410, 470)
    assert route.json()["follows_bells"] is True

    _generate(client, admin_headers, MONDAY)
    assert _run_window(client, admin_headers, MONDAY) == (410, 470)


def test_an_afternoon_route_leaves_after_dismissal(client, admin_headers):
    school = _school(client, admin_headers)
    _schedule(client, admin_headers, school, "Regular", 8 * 60, 15 * 60)
    route = _route(client, admin_headers, school, direction="pm").json()
    # Dismissal 15:00, leave 5-15 min after, then 45 minutes on the road.
    assert (route["window_earliest"], route["window_latest"]) == (905, 960)


def test_a_route_cant_follow_bells_its_school_doesnt_have(client, admin_headers):
    school = _school(client, admin_headers)
    response = _route(client, admin_headers, school)
    assert response.status_code == 400
    assert "no regular bell schedule" in response.json()["detail"]
    # Without bells, the window is required.
    manual = _route(client, admin_headers, school, follows_bells=False)
    assert manual.status_code == 400
    typed = _route(
        client,
        admin_headers,
        school,
        follows_bells=False,
        window_earliest=360,
        window_latest=450,
    )
    assert typed.status_code == 201
    assert typed.json()["follows_bells"] is False


def test_an_early_release_day_moves_that_days_runs_only(client, admin_headers):
    school = _school(client, admin_headers)
    _schedule(client, admin_headers, school, "Regular", 8 * 60, 15 * 60)
    early = _schedule(client, admin_headers, school, "Early release", 8 * 60, 12 * 60).json()
    assert early["is_regular"] is False
    _route(client, admin_headers, school, direction="pm")
    _generate(client, admin_headers, MONDAY)

    marked = client.put(
        "/bell-calendar",
        headers=admin_headers,
        json={"service_date": MONDAY, "schedule_name": "early release"},
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["runs_updated"] == 1
    # Already generated: moved to 12:00 dismissal.
    assert _run_window(client, admin_headers, MONDAY) == (725, 780)
    # Generated afterwards: the regular day.
    _generate(client, admin_headers, TUESDAY)
    assert _run_window(client, admin_headers, TUESDAY) == (905, 960)

    bells_read = client.get(f"/schools/{school['id']}/bells", headers=admin_headers).json()
    [day] = bells_read["upcoming_days"]
    assert (day["service_date"], day["schedule_name"]) == (MONDAY, "Early release")

    # Back to normal.
    cleared = client.delete(f"/bell-calendar/{day['id']}", headers=admin_headers)
    assert cleared.json()["runs_updated"] == 1
    assert _run_window(client, admin_headers, MONDAY) == (905, 960)


def test_marking_a_day_for_every_school_skips_those_without_that_schedule(client, admin_headers):
    north = _school(client, admin_headers, "North")
    south = _school(client, admin_headers, "South")
    _schedule(client, admin_headers, north, "Regular", 480, 900)
    _schedule(client, admin_headers, north, "Late start", 600, 900)
    _schedule(client, admin_headers, south, "Regular", 480, 900)

    every = client.put(
        "/bell-calendar",
        headers=admin_headers,
        json={"service_date": MONDAY, "schedule_name": "Late start"},
    )
    assert every.status_code == 200
    days = client.get("/bell-calendar", headers=admin_headers).json()
    assert [(d["school_name"], d["schedule_name"]) for d in days] == [("North", "Late start")]

    named = client.put(
        "/bell-calendar",
        headers=admin_headers,
        json={"service_date": TUESDAY, "schedule_name": "Late start", "school_ids": [south["id"]]},
    )
    assert named.status_code == 400

    both = client.put(
        "/bell-calendar",
        headers=admin_headers,
        json={
            "service_date": TUESDAY,
            "schedule_name": "Late start",
            "school_ids": [north["id"], south["id"]],
        },
    )
    assert both.json()["skipped_schools"] == ["South"]


def test_changing_a_bell_moves_upcoming_runs_and_dispatch_sees_what_no_longer_fits(
    client, admin_headers
):
    school = _school(client, admin_headers)
    regular = _schedule(client, admin_headers, school, "Regular", 8 * 60, 15 * 60).json()
    _route(client, admin_headers, school)
    driver = client.post(
        "/drivers", headers=admin_headers, json={"license_class": "cdl_a", "full_name": "Driver A"}
    ).json()
    vehicle = client.post("/vehicles", headers=admin_headers, json={"label": "Bus A"}).json()
    client.post(
        "/crew-templates",
        headers=admin_headers,
        json={
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 300,
            "available_window_latest": 1000,
            "days_of_week": WEEKDAYS,
        },
    )
    _generate(client, admin_headers, MONDAY)
    solved = client.post(
        "/schedule",
        headers=admin_headers,
        json={"service_date": MONDAY, "average_deadhead_speed_kmh": 40.0},
    )
    assert solved.status_code == 200, solved.text
    alerts = client.get("/alerts", headers=admin_headers, params={"service_date": MONDAY}).json()
    assert not [a for a in alerts["alerts"] if a["kind"] == "outside_window"]

    # The first bell moves an hour later: the assigned run no longer fits.
    moved = client.patch(
        f"/bell-schedules/{regular['id']}",
        headers=admin_headers,
        json={"first_bell_minute": 9 * 60},
    )
    assert moved.json() == {"runs_updated": 1, "assigned_runs_moved": 1, "skipped_schools": []}
    assert _run_window(client, admin_headers, MONDAY) == (470, 530)
    alerts = client.get("/alerts", headers=admin_headers, params={"service_date": MONDAY}).json()
    [alert] = [a for a in alerts["alerts"] if a["kind"] == "outside_window"]
    assert alert["severity"] == "critical"
    assert "Run the schedule again" in alert["message"]

    # Running the schedule again clears it.
    client.post(
        "/schedule",
        headers=admin_headers,
        json={"service_date": MONDAY, "average_deadhead_speed_kmh": 40.0},
    )
    alerts = client.get("/alerts", headers=admin_headers, params={"service_date": MONDAY}).json()
    assert not [a for a in alerts["alerts"] if a["kind"] == "outside_window"]


def test_past_days_and_routes_not_following_bells_keep_their_windows(client, admin_headers):
    school = _school(client, admin_headers)
    regular = _schedule(client, admin_headers, school, "Regular", 480, 900).json()
    _route(client, admin_headers, school)
    _route(
        client,
        admin_headers,
        school,
        direction="pm",
        follows_bells=False,
        window_earliest=900,
        window_latest=990,
    )
    past = "2026-07-27"  # before the pinned clock's 2026-08-01
    _generate(client, admin_headers, past)
    client.patch(
        f"/bell-schedules/{regular['id']}", headers=admin_headers, json={"first_bell_minute": 540}
    )
    runs = client.get("/runs", headers=admin_headers, params={"service_date": past}).json()
    assert sorted((r["window_earliest"], r["window_latest"]) for r in runs) == [
        (410, 470),
        (900, 990),
    ]


def test_a_school_can_have_its_own_windows(client, admin_headers):
    school = _school(client, admin_headers)
    _schedule(client, admin_headers, school, "Regular", 480, 900)
    route = _route(client, admin_headers, school).json()
    assert (route["window_earliest"], route["window_latest"]) == (410, 470)

    own = {
        "arrive_earliest_before": 20,
        "arrive_latest_before": 5,
        "leave_earliest_after": 0,
        "leave_latest_after": 10,
    }
    response = client.put(
        f"/schools/{school['id']}/bell-offsets", headers=admin_headers, json={"offsets": own}
    )
    assert response.status_code == 200
    read = client.get(f"/schools/{school['id']}/bells", headers=admin_headers).json()
    assert read["own_offsets"] == own
    [route] = client.get("/route-templates", headers=admin_headers).json()
    assert (route["window_earliest"], route["window_latest"]) == (415, 475)

    # Back to the district's.
    client.put(f"/schools/{school['id']}/bell-offsets", headers=admin_headers, json={})
    read = client.get(f"/schools/{school['id']}/bells", headers=admin_headers).json()
    assert read["own_offsets"] is None
    assert read["offsets_in_use"]["arrive_earliest_before"] == 25


def test_district_windows_are_validated_and_move_routes(client, admin_headers):
    assert client.get("/bell-rules", headers=admin_headers).json()["is_default"] is True
    school = _school(client, admin_headers)
    _schedule(client, admin_headers, school, "Regular", 480, 900)
    _route(client, admin_headers, school)

    backwards = {
        "arrive_earliest_before": 5,
        "arrive_latest_before": 20,
        "leave_earliest_after": 5,
        "leave_latest_after": 15,
    }
    assert client.put("/bell-rules", headers=admin_headers, json=backwards).status_code == 400
    wider = {
        "arrive_earliest_before": 30,
        "arrive_latest_before": 10,
        "leave_earliest_after": 5,
        "leave_latest_after": 15,
    }
    assert client.put("/bell-rules", headers=admin_headers, json=wider).status_code == 200
    rules = client.get("/bell-rules", headers=admin_headers).json()
    assert rules["is_default"] is False and rules["arrive_earliest_before"] == 30
    [route] = client.get("/route-templates", headers=admin_headers).json()
    assert route["window_earliest"] == 480 - 30 - 45


def test_schedule_rules(client, admin_headers):
    school = _school(client, admin_headers)
    regular = _schedule(client, admin_headers, school, "Regular", 480, 900).json()
    assert _schedule(client, admin_headers, school, "regular", 480, 900).status_code == 409
    assert _schedule(client, admin_headers, school, "Backwards", 900, 480).status_code == 422
    late = _schedule(client, admin_headers, school, "Late start", 600, 900, is_regular=True)
    assert late.json()["is_regular"] is True
    schedules = client.get(f"/schools/{school['id']}/bells", headers=admin_headers).json()
    assert [s["is_regular"] for s in schedules["schedules"]] == [True, False]  # by name

    # The regular one can't be deleted; an alternate can.
    late_id = late.json()["id"]
    assert client.delete(f"/bell-schedules/{late_id}", headers=admin_headers).status_code == 400
    assert (
        client.patch(
            f"/bell-schedules/{regular['id']}", headers=admin_headers, json={"is_regular": True}
        ).status_code
        == 200
    )
    assert client.delete(f"/bell-schedules/{late_id}", headers=admin_headers).status_code == 200


def test_csv_import_previews_then_applies(client, admin_headers, db_session):
    _school(client, admin_headers, "North High")
    _school(client, admin_headers, "South Middle")
    text = (
        "School,Schedule,First_bell,Dismissal\n"
        "North High,Regular,07:30,14:45\n"
        "North High,Early release,07:30,11:45\n"
        "South Middle,Regular,8:15,15:30\n"
        "Nowhere,Regular,08:00,15:00\n"
        "South Middle,Late start,25:00,15:30\n"
    )
    preview = client.post("/bell-schedules/import", headers=admin_headers, json={"csv": text})
    assert preview.status_code == 200, preview.text
    assert preview.json()["applied"] is False
    assert [r["outcome"] for r in preview.json()["rows"]] == [
        "created",
        "created",
        "created",
        "error",
        "error",
    ]
    assert client.get("/bell-calendar", headers=admin_headers).status_code == 200
    schools = client.get("/schools", headers=admin_headers).json()
    north = next(s for s in schools if s["name"] == "North High")
    assert (
        client.get(f"/schools/{north['id']}/bells", headers=admin_headers).json()["schedules"] == []
    )

    applied = client.post(
        "/bell-schedules/import",
        headers=admin_headers,
        params={"dry_run": "false"},
        json={"csv": text},
    )
    assert applied.json()["applied"] is True
    schedules = client.get(f"/schools/{north['id']}/bells", headers=admin_headers).json()[
        "schedules"
    ]
    assert [(s["name"], s["first_bell_minute"], s["is_regular"]) for s in schedules] == [
        ("Early release", 450, False),
        ("Regular", 450, True),
    ]
    again = client.post(
        "/bell-schedules/import",
        headers=admin_headers,
        params={"dry_run": "false"},
        json={"csv": text},
    )
    assert [r["outcome"] for r in again.json()["rows"]][:3] == ["unchanged"] * 3
    assert db_session.query(AuditLogEntry).filter_by(action="imported").count() == 2

    no_header = client.post("/bell-schedules/import", headers=admin_headers, json={"csv": "a,b\n"})
    assert no_header.status_code == 400


def test_csv_import_never_guesses_between_schools_with_one_name(client, admin_headers):
    _school(client, admin_headers, "Twin")
    _school(client, admin_headers, "twin")
    twins = client.post(
        "/bell-schedules/import",
        headers=admin_headers,
        json={"csv": "school,schedule,first_bell,dismissal\nTwin,Regular,08:00,15:00\n"},
    )
    [row] = twins.json()["rows"]
    assert row["outcome"] == "error"
    assert "More than one school" in row["message"]


def test_who_can_see_and_change_bells(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    other = _school(client, admin_headers, "Other")
    _schedule(client, admin_headers, school, "Regular", 480, 900)

    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="disp@example.org"))
    assert client.get(f"/schools/{school['id']}/bells", headers=dispatcher).status_code == 200
    assert client.get("/bell-rules", headers=dispatcher).status_code == 200
    assert _schedule(client, dispatcher, school, "Late", 600, 900).status_code == 403

    make_user(
        db_session, email="principal@example.org", role=Role.SCHOOL_ADMIN, school_id=school["id"]
    )
    principal = auth_headers(login(client, email="principal@example.org"))
    mine = client.get(f"/schools/{school['id']}/bells", headers=principal)
    assert mine.status_code == 200
    assert mine.json()["schedules"][0]["first_bell_minute"] == 480
    assert client.get(f"/schools/{other['id']}/bells", headers=principal).status_code == 403
    assert _schedule(client, principal, school, "Late", 600, 900).status_code == 403
    assert client.get("/bell-calendar", headers=principal).status_code == 403

    make_user(db_session, email="parent@example.org", role=Role.PARENT)
    parent = auth_headers(login(client, email="parent@example.org"))
    assert client.get(f"/schools/{school['id']}/bells", headers=parent).status_code == 403


def test_bell_changes_are_audited(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    regular = _schedule(client, admin_headers, school, "Regular", 480, 900).json()
    _route(client, admin_headers, school)
    _generate(client, admin_headers, MONDAY)
    client.patch(
        f"/bell-schedules/{regular['id']}", headers=admin_headers, json={"first_bell_minute": 500}
    )
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert {"created", "updated", "window_from_bells"} <= actions
