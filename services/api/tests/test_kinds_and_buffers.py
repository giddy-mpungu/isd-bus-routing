"""Depth from the October review, part 2: kinds of route and trip (spec
section 11) and a route's buffer by reason (section 16)."""

DAY = "2026-10-26"  # a Monday


def _school(client, h):
    return client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()


def _route(client, h, school, **extra):
    return client.post(
        "/route-templates",
        headers=h,
        json={
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 420,
            "window_latest": 480,
            "duration_minutes": 30,
            "days_of_week": [0, 1, 2, 3, 4],
            **extra,
        },
    )


def test_a_routes_kind_reaches_its_runs(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    route = _route(client, h, school, kind="special_education").json()
    assert route["kind"] == "special_education"
    assert client.post(f"/schedule/{DAY}/generate-from-templates", headers=h).status_code == 200
    [run] = client.get("/runs", headers=h, params={"service_date": DAY}).json()
    assert run["kind"] == "special_education"

    changed = client.patch(
        f"/route-templates/{route['id']}", headers=h, json={"kind": "shuttle"}
    ).json()
    assert changed["kind"] == "shuttle"


def test_the_buffer_is_the_sum_of_its_reasons(client, admin_headers):
    h = admin_headers
    school = _school(client, h)
    route = _route(
        client, h, school, buffer_breakdown={"traffic": 5, "rail_crossings": 3, "fueling": 0}
    ).json()
    assert route["buffer_minutes"] == 8
    # Zero reasons are left out; the order is the spec's.
    assert route["buffer_breakdown"] == {"traffic": 5, "rail_crossings": 3}

    updated = client.patch(
        f"/route-templates/{route['id']}",
        headers=h,
        json={"buffer_breakdown": {"loading": 4, "wheelchair": 6}},
    ).json()
    assert (updated["buffer_minutes"], updated["buffer_breakdown"]) == (
        10,
        {"loading": 4, "wheelchair": 6},
    )

    # Too much for the 60-minute window with a 30-minute route.
    too_much = client.patch(
        f"/route-templates/{route['id']}",
        headers=h,
        json={"buffer_breakdown": {"weather": 40}},
    )
    assert too_much.status_code == 400
    assert "don't fit" in too_much.json()["detail"]

    # Cleared: the total stays, its reasons go.
    cleared = client.patch(
        f"/route-templates/{route['id']}", headers=h, json={"buffer_breakdown": None}
    ).json()
    assert (cleared["buffer_minutes"], cleared["buffer_breakdown"]) == (10, None)


def test_only_known_reasons_and_sensible_minutes(client, admin_headers):
    school = _school(client, admin_headers)
    for bad in ({"vibes": 5}, {"traffic": -1}, {"traffic": 500}):
        assert _route(client, admin_headers, school, buffer_breakdown=bad).status_code == 422


def test_a_trips_kind_is_kept(client, admin_headers):
    h = admin_headers
    trip = client.post(
        "/field-trips",
        headers=h,
        json={
            "requesting_party": "Varsity soccer",
            "origin": "Riverside",
            "destination": "Northside stadium",
            "departure_at": f"{DAY}T15:00:00",
            "expected_return_at": f"{DAY}T19:00:00",
            "trip_contact": "Coach Lee",
            "kind": "athletic",
        },
    ).json()
    assert trip["kind"] == "athletic"
    plain = client.patch(f"/field-trips/{trip['id']}", headers=h, json={"kind": "activity"}).json()
    assert plain["kind"] == "activity"
