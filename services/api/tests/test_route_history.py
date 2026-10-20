"""Learning from history (spec sections 13 and 20): a route's observed time,
a route's duration adjusted toward it, and substitutes who've driven the
route before ranked first."""

from tests.test_observed_run_duration import _complete_assignment_with_duration

DAY_1, DAY_2 = "2026-09-01", "2026-09-02"


def _school_and_route(client, h):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    route = client.post(
        "/route-templates",
        headers=h,
        json={
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 420,
            "window_latest": 480,
            "duration_minutes": 30,
            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
        },
    ).json()
    return school, route


def _driver(client, h, name):
    return client.post(
        "/drivers", headers=h, json={"full_name": name, "license_class": "cdl_a"}
    ).json()


def _crew(client, h, driver, day, window=(360, 1000)):
    vehicle = client.post(
        "/vehicles",
        headers=h,
        json={"label": f"Bus of {driver['full_name']} {day}", "nominal_capacity": 40},
    ).json()
    return client.post(
        "/crews",
        headers=h,
        json={
            "service_date": day,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": window[0],
            "available_window_latest": window[1],
        },
    ).json()


def _solve_day(client, h, day):
    assert client.post(f"/schedule/{day}/generate-from-templates", headers=h).status_code == 200
    response = client.post("/schedule", headers=h, json={"service_date": day})
    assert response.status_code == 200, response.text
    return response.json()["assignments"]


def test_a_routes_duration_can_be_adjusted_within_its_window(client, admin_headers):
    _, route = _school_and_route(client, admin_headers)
    response = client.patch(
        f"/route-templates/{route['id']}", headers=admin_headers, json={"duration_minutes": 48}
    )
    assert response.status_code == 200, response.text
    assert response.json()["duration_minutes"] == 48
    too_long = client.patch(
        f"/route-templates/{route['id']}", headers=admin_headers, json={"duration_minutes": 70}
    )
    assert too_long.status_code == 400
    assert "don't fit the route's 60-minute window" in too_long.json()["detail"]


def test_a_routes_observed_time_counts_only_its_own_runs(client, admin_headers, db_session):
    h = admin_headers
    school, route = _school_and_route(client, h)
    sam = _driver(client, h, "Sam")
    _crew(client, h, sam, DAY_1)
    [on_route] = _solve_day(client, h, DAY_1)
    _complete_assignment_with_duration(
        client, h, db_session, sam["id"], on_route["id"], actual_minutes=48
    )
    # A one-off run at the same school, the same way, not on the route.
    casey = _driver(client, h, "Casey")
    _crew(client, h, casey, DAY_2)
    client.post(
        "/runs",
        headers=h,
        json={
            "service_date": DAY_2,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 420,
            "window_latest": 480,
            "duration_minutes": 30,
        },
    )
    client.patch(f"/route-templates/{route['id']}", headers=h, json={"is_active": False})
    [one_off] = client.post("/schedule", headers=h, json={"service_date": DAY_2}).json()[
        "assignments"
    ]
    _complete_assignment_with_duration(
        client, h, db_session, casey["id"], one_off["id"], actual_minutes=30
    )

    params = {"school_id": school["id"], "direction": "am"}
    every_run = client.get("/runs/observed-duration", headers=h, params=params).json()
    this_route = client.get(
        "/runs/observed-duration",
        headers=h,
        params={**params, "route_template_id": route["id"]},
    ).json()
    assert every_run["sample_count"] == 2
    assert (this_route["sample_count"], this_route["average_actual_minutes"]) == (1, 48.0)


def test_a_substitute_who_has_driven_the_route_comes_first(client, admin_headers):
    h = admin_headers
    _school_and_route(client, h)
    sam, casey, pat = (_driver(client, h, name) for name in ("Sam", "Casey", "Pat"))
    _crew(client, h, sam, DAY_1)
    _solve_day(client, h, DAY_1)  # Sam drives the route on day 1
    _crew(client, h, pat, DAY_2)
    _solve_day(client, h, DAY_2)  # Pat on day 2, and is out sick

    [affected] = client.get(
        f"/drivers/{pat['id']}/substitute-candidates",
        headers=h,
        params={"service_date": DAY_2},
    ).json()
    first, second = affected["candidates"][:2]
    assert (first["driver_id"], second["driver_id"]) == (sam["id"], casey["id"])
    assert "has driven this route 1 time(s) before" in first["reasons"]


def test_a_substitute_who_would_break_the_districts_rules_isnt_offered(client, admin_headers):
    h = admin_headers
    school, _ = _school_and_route(client, h)
    sam, pat = _driver(client, h, "Sam"), _driver(client, h, "Pat")
    # Sam already works the afternoon on day 2; Pat, the morning.
    _crew(client, h, sam, DAY_2, window=(840, 1000))
    client.post(
        "/runs",
        headers=h,
        json={
            "service_date": DAY_2,
            "school_id": school["id"],
            "direction": "pm",
            "window_earliest": 900,
            "window_latest": 960,
            "duration_minutes": 60,
        },
    )
    _crew(client, h, pat, DAY_2, window=(360, 600))
    _solve_day(client, h, DAY_2)
    client.put(
        "/optimization-settings",
        headers=h,
        json={
            "crews_used_weight": 1,
            "deadhead_minutes_weight": 0,
            "arrival_buffer_weight": 0,
            "max_duty_minutes": 6 * 60,
        },
    )
    affected = client.get(
        f"/drivers/{pat['id']}/substitute-candidates",
        headers=h,
        params={"service_date": DAY_2},
    ).json()
    am = next(a for a in affected if a["start_minute"] < 720)
    # 07:00 to 16:00 would be nine hours for Sam, over the six-hour day.
    assert sam["id"] not in [c["driver_id"] for c in am["candidates"]]
