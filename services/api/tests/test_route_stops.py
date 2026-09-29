"""Ordered stops on recurring routes (spec sections 3, 9), and attributing
riders to one of several runs on a leg by their stop."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user

DAY = "2026-10-05"  # a Monday


def _school(client, h, name="Riverside"):
    return client.post(
        "/schools",
        headers=h,
        json={"name": name, "location_lat": 29.7, "location_lon": -95.4},
    ).json()


def _stop(client, h, label, lat):
    return client.post(
        "/stops", headers=h, json={"label": label, "location_lat": lat, "location_lon": -95.4}
    ).json()


def _route(client, h, school, earliest=420, duration=40):
    response = client.post(
        "/route-templates",
        headers=h,
        json={
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": earliest,
            "window_latest": earliest + 60,
            "duration_minutes": duration,
            "days_of_week": [0, 1, 2, 3, 4],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_stops(client, h, route, *items):
    return client.put(
        f"/route-templates/{route['id']}/stops",
        headers=h,
        json={
            "stops": [
                {"stop_id": stop["id"], "minutes_from_start": minutes} for stop, minutes in items
            ]
        },
    )


def _student(client, h, school, name, stop=None):
    body = {"full_name": name, "school_id": school["id"]}
    if stop is not None:
        body["stop_id"] = stop["id"]
    return client.post("/students", headers=h, json=body).json()


def _crew(client, h, label, db_session=None):
    driver = client.post(
        "/drivers", headers=h, json={"full_name": f"Driver {label}", "license_class": "cdl_b"}
    ).json()
    vehicle = client.post(
        "/vehicles", headers=h, json={"label": f"Bus {label}", "nominal_capacity": 48}
    ).json()
    client.post(
        "/crews",
        headers=h,
        json={
            "service_date": DAY,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 360,
            "available_window_latest": 1000,
        },
    )
    if db_session is not None:
        email = f"driver.{label.lower()}@example.org"
        make_user(db_session, email=email, role=Role.DRIVER, driver_id=driver["id"])
        return driver, auth_headers(login(client, email=email))
    return driver, None


def _generate_and_solve(client, h):
    generated = client.post(f"/schedule/{DAY}/generate-from-templates", headers=h)
    assert generated.status_code == 200, generated.text
    solved = client.post("/schedule", headers=h, json={"service_date": DAY})
    assert solved.status_code == 200, solved.text
    return solved.json()["assignments"]


def _runs(client, h):
    return client.get("/runs", headers=h, params={"service_date": DAY}).json()


# --- Editing a route's stops -------------------------------------------------


def test_a_route_keeps_its_stops_in_order_and_edits_are_audited(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    oak, elm, pine = (
        _stop(client, admin_headers, n, 29.71 + i / 100)
        for i, n in enumerate(["Oak", "Elm", "Pine"])
    )
    route = _route(client, admin_headers, school)

    response = _set_stops(client, admin_headers, route, (oak, 0), (elm, 8), (pine, None))
    assert response.status_code == 200, response.text
    assert [(s["position"], s["stop_label"], s["minutes_from_start"]) for s in response.json()] == [
        (1, "Oak", 0),
        (2, "Elm", 8),
        (3, "Pine", None),
    ]
    assert response.json()[0]["location_lat"] == 29.71

    # Reordering replaces the list.
    reordered = _set_stops(client, admin_headers, route, (pine, 0), (oak, 5), (elm, 12))
    assert [s["stop_label"] for s in reordered.json()] == ["Pine", "Oak", "Elm"]
    [listed] = client.get("/route-templates", headers=admin_headers).json()
    assert [s["stop_label"] for s in listed["stops"]] == ["Pine", "Oak", "Elm"]

    entries = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "route_template", AuditLogEntry.action == "stops_updated"
        )
        .order_by(AuditLogEntry.id)
        .all()
    )
    assert len(entries) == 2
    assert [s["stop_id"] for s in entries[1].before_state["stops"]] == [
        oak["id"],
        elm["id"],
        pine["id"],
    ]
    assert [s["stop_id"] for s in entries[1].after_state["stops"]] == [
        pine["id"],
        oak["id"],
        elm["id"],
    ]


def test_route_stops_are_validated(client, admin_headers):
    school = _school(client, admin_headers)
    oak = _stop(client, admin_headers, "Oak", 29.71)
    elm = _stop(client, admin_headers, "Elm", 29.72)
    route = _route(client, admin_headers, school, duration=40)

    twice = _set_stops(client, admin_headers, route, (oak, 0), (oak, 5))
    assert twice.status_code == 400 and "only once" in twice.json()["detail"]
    unknown = _set_stops(client, admin_headers, route, ({"id": 999}, 0))
    assert unknown.status_code == 400
    backwards = _set_stops(client, admin_headers, route, (oak, 10), (elm, 5))
    assert backwards.status_code == 400 and "backwards" in backwards.json()["detail"]
    too_late = _set_stops(client, admin_headers, route, (oak, 0), (elm, 41))
    assert too_late.status_code == 400 and "40-minute" in too_late.json()["detail"]
    assert client.get(f"/route-templates/{route['id']}/stops", headers=admin_headers).json() == []


def test_dispatchers_edit_route_stops_and_drivers_cannot(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    oak = _stop(client, admin_headers, "Oak", 29.71)
    route = _route(client, admin_headers, school)
    make_user(db_session, email="d@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="d@example.org"))
    assert _set_stops(client, dispatcher, route, (oak, 0)).status_code == 200
    _, driver = _crew(client, admin_headers, "A", db_session)
    assert _set_stops(client, driver, route, (oak, 0)).status_code == 403


def test_a_stop_on_a_route_cannot_be_deleted(client, admin_headers):
    school = _school(client, admin_headers)
    oak = _stop(client, admin_headers, "Oak", 29.71)
    route = _route(client, admin_headers, school)
    _set_stops(client, admin_headers, route, (oak, 0))
    refused = client.delete(f"/stops/{oak['id']}", headers=admin_headers)
    assert refused.status_code == 409 and "on 1 route" in refused.json()["detail"]
    _set_stops(client, admin_headers, route)
    assert client.delete(f"/stops/{oak['id']}", headers=admin_headers).status_code == 204


# --- The driver's roster follows the route -----------------------------------


def test_the_drivers_stops_follow_the_route_with_planned_times(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    oak = _stop(client, admin_headers, "Oak", 29.71)
    elm = _stop(client, admin_headers, "Elm", 29.72)
    pine = _stop(client, admin_headers, "Pine", 29.73)
    maple = _stop(client, admin_headers, "Maple", 29.74)
    route = _route(client, admin_headers, school)
    _set_stops(client, admin_headers, route, (elm, 0), (oak, 7), (pine, None))
    _student(client, admin_headers, school, "Ana", oak)
    _student(client, admin_headers, school, "Ben", elm)
    _student(client, admin_headers, school, "Cy", elm)
    _student(client, admin_headers, school, "Dee", maple)  # stop not on the route
    _, driver = _crew(client, admin_headers, "A", db_session)
    [assignment] = _generate_and_solve(client, admin_headers)

    [mine] = client.get(f"/schedule/{DAY}/my-assignments", headers=driver).json()
    assert mine["stops_ordered"] is True and mine["roster_ambiguous"] is False
    start = assignment["start_minute"]
    assert [
        (s["position"], s["stop_label"], s["planned_minute"], s["student_names"], s["on_route"])
        for s in mine["stops"]
    ] == [
        (1, "Elm", start, ["Ben", "Cy"], True),
        (2, "Oak", start + 7, ["Ana"], True),
        (3, "Pine", None, [], True),  # nobody rides from Pine today, still listed
        (None, "Maple", None, ["Dee"], False),
    ]


def test_a_run_without_route_stops_keeps_the_grouped_roster(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    oak = _stop(client, admin_headers, "Oak", 29.71)
    _route(client, admin_headers, school)
    _student(client, admin_headers, school, "Ana", oak)
    _, driver = _crew(client, admin_headers, "A", db_session)
    _generate_and_solve(client, admin_headers)
    [mine] = client.get(f"/schedule/{DAY}/my-assignments", headers=driver).json()
    assert mine["stops_ordered"] is False
    assert [(s["stop_label"], s["position"]) for s in mine["stops"]] == [("Oak", None)]


# --- Several runs on one leg -------------------------------------------------


def _two_routes(client, h, db_session):
    school = _school(client, h)
    north = _stop(client, h, "North", 29.75)
    east = _stop(client, h, "East", 29.76)
    south = _stop(client, h, "South", 29.65)
    nowhere = _stop(client, h, "Nowhere", 29.9)
    route_n = _route(client, h, school, earliest=420)
    route_s = _route(client, h, school, earliest=425)
    _set_stops(client, h, route_n, (north, 0), (east, 5))
    _set_stops(client, h, route_s, (south, 0))
    students = {
        "Ana": _student(client, h, school, "Ana", north),
        "Ben": _student(client, h, school, "Ben", east),
        "Cy": _student(client, h, school, "Cy", south),
        "Dee": _student(client, h, school, "Dee", nowhere),
        "Eve": _student(client, h, school, "Eve"),
    }
    _crew(client, h, "A", db_session)
    _crew(client, h, "B", db_session)
    _generate_and_solve(client, h)
    runs = {r["route_template_id"]: r for r in _runs(client, h)}
    return (
        school,
        students,
        runs[route_n["id"]],
        runs[route_s["id"]],
        (route_n, route_s, north, south),
    )


def test_riders_are_attributed_to_the_run_whose_route_has_their_stop(
    client, admin_headers, db_session
):
    _, _, north_run, south_run, _ = _two_routes(client, admin_headers, db_session)
    north = client.get(f"/runs/{north_run['id']}/expected-riders", headers=admin_headers).json()
    south = client.get(f"/runs/{south_run['id']}/expected-riders", headers=admin_headers).json()
    assert (north["ambiguous"], north["expected_passenger_count"]) == (False, 2)
    assert sorted(north["riding_student_names"]) == ["Ana", "Ben"]
    assert (south["ambiguous"], south["riding_student_names"]) == (False, ["Cy"])


def test_a_family_sees_the_bus_whose_route_has_their_stop(client, admin_headers, db_session):
    _, students, north_run, _, _ = _two_routes(client, admin_headers, db_session)
    parents = {}
    for name in ("Ana", "Dee", "Eve"):
        email = f"parent.{name.lower()}@example.org"
        user = make_user(db_session, email=email, role=Role.PARENT)
        client.post(
            f"/students/{students[name]['id']}/guardians",
            headers=admin_headers,
            json={"user_id": user.id},
        )
        parents[name] = auth_headers(login(client, email=email))

    def locate(name):
        return client.get(
            f"/students/{students[name]['id']}/bus-position",
            headers=parents[name],
            params={"service_date": DAY, "direction": "am"},
        ).json()

    # Ana's stop is on the north route: not ambiguous (no GPS yet, so not available).
    assert locate("Ana") == {**locate("Ana"), "ambiguous": False, "available": False}
    # Dee's stop is on no route, and Eve has no stop: still ambiguous, never a guess.
    assert locate("Dee")["ambiguous"] is True
    assert locate("Eve")["ambiguous"] is True


def test_a_stop_on_two_routes_of_one_leg_is_not_attributed(client, admin_headers, db_session):
    _, students, north_run, south_run, (route_n, route_s, north, south) = _two_routes(
        client, admin_headers, db_session
    )
    _set_stops(client, admin_headers, route_s, (south, 0), (north, 5))
    north_riders = client.get(
        f"/runs/{north_run['id']}/expected-riders", headers=admin_headers
    ).json()["riding_student_names"]
    south_riders = client.get(
        f"/runs/{south_run['id']}/expected-riders", headers=admin_headers
    ).json()["riding_student_names"]
    assert "Ana" not in north_riders and "Ana" not in south_riders


def test_a_run_without_route_stops_on_a_shared_leg_stays_ambiguous(client, admin_headers):
    school = _school(client, admin_headers)
    oak = _stop(client, admin_headers, "Oak", 29.71)
    _student(client, admin_headers, school, "Ana", oak)
    for earliest in (420, 430):
        client.post(
            "/runs",
            headers=admin_headers,
            json={
                "service_date": DAY,
                "school_id": school["id"],
                "direction": "am",
                "window_earliest": earliest,
                "window_latest": earliest + 60,
                "duration_minutes": 30,
            },
        )
    for run in _runs(client, admin_headers):
        body = client.get(f"/runs/{run['id']}/expected-riders", headers=admin_headers).json()
        assert body["ambiguous"] is True
