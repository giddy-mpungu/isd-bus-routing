"""Field trips are jobs in the same scheduling engine as regular routes
(spec sections 12, 12.1, 12.2): an assigned trip is busy time for its
driver and its bus, padded by a turnaround margin, everywhere work is
assigned."""

from isd_api.availability import FIELD_TRIP_TURNAROUND_MINUTES

DAY = "2026-10-08"


def _school(client, h):
    return client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()


def _driver(client, h, name):
    return client.post("/drivers", headers=h, json={"full_name": name}).json()


def _vehicle(client, h, label):
    return client.post("/vehicles", headers=h, json={"label": label}).json()


def _crew(client, h, label, *, earliest=360, latest=1000, day=DAY):
    driver = _driver(client, h, f"Driver {label}")
    vehicle = _vehicle(client, h, f"Bus {label}")
    response = client.post(
        "/crews",
        headers=h,
        json={
            "service_date": day,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": earliest,
            "available_window_latest": latest,
        },
    )
    assert response.status_code == 201, response.text
    return driver, vehicle, response.json()


def _run(client, h, school, earliest, latest, *, duration=30, day=DAY):
    response = client.post(
        "/runs",
        headers=h,
        json={
            "service_date": day,
            "school_id": school["id"],
            "direction": "pm" if earliest >= 720 else "am",
            "window_earliest": earliest,
            "window_latest": latest,
            "duration_minutes": duration,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _trip(client, h, depart="09:00", back="13:30", *, day=DAY, back_day=None):
    response = client.post(
        "/field-trips",
        headers=h,
        json={
            "requesting_party": "Riverside 5th grade",
            "origin": "Riverside",
            "destination": "Science Museum",
            "departure_at": f"{day}T{depart}:00",
            "expected_return_at": f"{back_day or day}T{back}:00",
            "passenger_count": 30,
            "trip_contact": "Ms. Patel",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assign(client, h, trip, driver=None, vehicle=None):
    body = {"status": "assigned"}
    if driver:
        body["assigned_driver_id"] = driver["id"]
    if vehicle:
        body["assigned_vehicle_id"] = vehicle["id"]
    return client.patch(f"/field-trips/{trip['id']}", headers=h, json=body)


def _solve(client, h, day=DAY):
    return client.post("/schedule", headers=h, json={"service_date": day})


def _assignments(client, h, day=DAY):
    return client.get(f"/schedule/{day}/assignments", headers=h).json()


def _by_run(response):
    return {a["run_id"]: a["crew_id"] for a in response.json()["assignments"]}


# --- The solver respects trips ----------------------------------------------


def test_a_trip_keeps_its_driver_off_overlapping_routes(client, admin_headers):
    # Crew A can do both runs alone (the solver's unique best plan). Once
    # A's driver has an afternoon trip, the 14:15 run must go to C.
    school = _school(client, admin_headers)
    a_driver, _, a_crew = _crew(client, admin_headers, "A")
    _crew(client, admin_headers, "B", latest=600)
    _, _, c_crew = _crew(client, admin_headers, "C", earliest=800)
    _run(client, admin_headers, school, 400, 440)
    afternoon = _run(client, admin_headers, school, 855, 900)
    assert set(_by_run(_solve(client, admin_headers)).values()) == {a_crew["id"]}

    trip = _trip(client, admin_headers, "12:00", "16:30")
    assert _assign(client, admin_headers, trip, driver=a_driver).status_code == 200

    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert _by_run(response)[afternoon["id"]] == c_crew["id"]


def test_a_trip_also_holds_its_bus(client, admin_headers):
    # Same shape as above, but only A's *bus* goes on the trip, driven by
    # someone with no crew today; A's own driver is free.
    school = _school(client, admin_headers)
    _, a_vehicle, a_crew = _crew(client, admin_headers, "A")
    _crew(client, admin_headers, "B", latest=600)
    _, _, c_crew = _crew(client, admin_headers, "C", earliest=800)
    _run(client, admin_headers, school, 400, 440)
    afternoon = _run(client, admin_headers, school, 855, 900)
    assert set(_by_run(_solve(client, admin_headers)).values()) == {a_crew["id"]}

    trip = _trip(client, admin_headers, "12:00", "16:30")
    trip_driver = _driver(client, admin_headers, "Trip Driver")
    assigned = _assign(client, admin_headers, trip, driver=trip_driver, vehicle=a_vehicle)
    assert assigned.status_code == 200, assigned.text

    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert _by_run(response)[afternoon["id"]] == c_crew["id"]


def test_a_multi_day_trip_takes_the_crew_out_for_the_whole_middle_day(client, admin_headers):
    day = "2026-10-09"
    school = _school(client, admin_headers)
    a_driver, _, a_crew = _crew(client, admin_headers, "A", day=day)
    _, _, b_crew = _crew(client, admin_headers, "B", latest=600, day=day)
    _, _, c_crew = _crew(client, admin_headers, "C", earliest=800, day=day)
    _run(client, admin_headers, school, 400, 440, day=day)
    _run(client, admin_headers, school, 855, 900, day=day)
    assert set(_by_run(_solve(client, admin_headers, day=day)).values()) == {a_crew["id"]}

    trip = _trip(client, admin_headers, "08:00", "18:00", day="2026-10-08", back_day="2026-10-10")
    assert _assign(client, admin_headers, trip, driver=a_driver).status_code == 200

    response = _solve(client, admin_headers, day=day)
    assert response.status_code == 200, response.text
    assert set(_by_run(response).values()) == {b_crew["id"], c_crew["id"]}


# --- Delay management (spec 12.2) -------------------------------------------


def test_the_specs_delay_example_flags_the_route_needing_cover(client, admin_headers):
    # Original return 13:30, updated to 15:00, normal route 14:15.
    school = _school(client, admin_headers)
    driver, _, crew = _crew(client, admin_headers, "A")
    _, _, other_crew = _crew(client, admin_headers, "B")
    route = _run(client, admin_headers, school, 855, 900)
    trip = _trip(client, admin_headers, "09:00", "13:30")
    assert _assign(client, admin_headers, trip, driver=driver).status_code == 200
    # Pin the route on this driver's crew, as the normal schedule would.
    [assignment] = _solve(client, admin_headers).json()["assignments"]
    if assignment["crew_id"] != crew["id"]:
        client.patch(
            f"/schedule/assignments/{assignment['id']}",
            headers=admin_headers,
            json={"crew_id": crew["id"]},
        )
    [before] = _assignments(client, admin_headers)
    assert before["crew_id"] == crew["id"] and before["availability_issue"] is None

    delayed = client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"expected_return_at": f"{DAY}T15:00:00"},
    )
    assert delayed.status_code == 200, delayed.text

    [flagged] = _assignments(client, admin_headers)
    assert flagged["availability_issue"].startswith(f"on field trip #{trip['id']} to Science")
    conflicts = client.get(f"/field-trips/{trip['id']}/conflicts", headers=admin_headers).json()
    assert len(conflicts["routes_needing_cover"]) == 1
    assert "Riverside" in conflicts["routes_needing_cover"][0]

    # Re-solving moves the (unlocked) route to the free crew.
    assert _by_run(_solve(client, admin_headers)) == {route["id"]: other_crew["id"]}


def test_a_recorded_early_actual_return_releases_the_driver(client, admin_headers):
    school = _school(client, admin_headers)
    driver, _, crew = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 855, 900)
    trip = _trip(client, admin_headers, "09:00", "16:30")
    assert _assign(client, admin_headers, trip, driver=driver).status_code == 200
    assert _solve(client, admin_headers).status_code == 422  # only crew is on the trip

    client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"actual_return_at": f"{DAY}T12:00:00"},
    )
    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert set(_by_run(response).values()) == {crew["id"]}


def test_turnaround_margin_counts_as_a_conflict(client, admin_headers):
    # A route ending 08:50 leaves 10 minutes before a 09:00 departure:
    # inside the margin. One ending 08:30 leaves 30: fine.
    assert FIELD_TRIP_TURNAROUND_MINUTES == 15
    school = _school(client, admin_headers)
    driver, _, _ = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 490, 530, duration=40)  # 08:10-08:50
    _solve(client, admin_headers)
    trip = _trip(client, admin_headers, "09:00", "13:30")
    tight = client.get(
        f"/field-trips/{trip['id']}/conflicts",
        headers=admin_headers,
        params={"driver_id": driver["id"]},
    ).json()
    assert len(tight["routes_needing_cover"]) == 1
    assert tight["turnaround_minutes"] == 15

    later_trip = _trip(client, admin_headers, "09:20", "13:30")
    roomy = client.get(
        f"/field-trips/{later_trip['id']}/conflicts",
        headers=admin_headers,
        params={"driver_id": driver["id"]},
    ).json()
    assert roomy["routes_needing_cover"] == []


# --- Assigning a trip (spec 12.1) -------------------------------------------


def test_assigning_an_unusable_driver_or_bus_is_refused(client, admin_headers):
    trip = _trip(client, admin_headers)

    bus = _vehicle(client, admin_headers, "Broken Bus")
    client.patch(f"/vehicles/{bus['id']}", headers=admin_headers, json={"is_active": False})
    refused = _assign(client, admin_headers, trip, vehicle=bus)
    assert refused.status_code == 409 and "out of service" in refused.json()["detail"]

    gone = _driver(client, admin_headers, "Gone")
    client.patch(f"/drivers/{gone['id']}", headers=admin_headers, json={"is_active": False})
    refused = _assign(client, admin_headers, trip, driver=gone)
    assert refused.status_code == 409 and "deactivated" in refused.json()["detail"]

    sick = _driver(client, admin_headers, "Sick")
    client.post(
        f"/drivers/{sick['id']}/absences",
        headers=admin_headers,
        json={"service_date": DAY, "start_minute": 600, "end_minute": 660, "reason": "sick_leave"},
    )
    refused = _assign(client, admin_headers, trip, driver=sick)
    assert refused.status_code == 409 and "absent" in refused.json()["detail"]

    busy = _driver(client, admin_headers, "Busy")
    first = _trip(client, admin_headers, "10:00", "12:00")
    assert _assign(client, admin_headers, first, driver=busy).status_code == 200
    refused = _assign(client, admin_headers, trip, driver=busy)
    assert refused.status_code == 409 and f"Field trip #{first['id']}" in refused.json()["detail"]

    assert (
        client.get(f"/field-trips/{trip['id']}", headers=admin_headers).json()["assigned_driver_id"]
        is None
    )


def test_a_regular_route_clash_does_not_block_assignment_but_flags_the_route(client, admin_headers):
    school = _school(client, admin_headers)
    driver, _, _ = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 600, 660)  # 10:00-11:00
    _solve(client, admin_headers)
    trip = _trip(client, admin_headers, "09:00", "13:30")

    assert _assign(client, admin_headers, trip, driver=driver).status_code == 200
    [flagged] = _assignments(client, admin_headers)
    assert flagged["availability_issue"].startswith(f"on field trip #{trip['id']}")


# --- Other paths use the same rule ------------------------------------------


def test_substitute_ranking_leaves_out_drivers_on_a_trip(client, admin_headers):
    school = _school(client, admin_headers)
    driver, _, _ = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 600, 660)
    _solve(client, admin_headers)
    on_trip = _driver(client, admin_headers, "On Trip")
    free = _driver(client, admin_headers, "Free")
    trip = _trip(client, admin_headers, "09:00", "13:30")
    assert _assign(client, admin_headers, trip, driver=on_trip).status_code == 200

    [affected] = client.get(
        f"/drivers/{driver['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": DAY},
    ).json()
    ids = {c["driver_id"] for c in affected["candidates"]}
    assert free["id"] in ids and on_trip["id"] not in ids


def test_repointing_a_crew_to_a_driver_on_a_trip_is_refused(client, admin_headers):
    school = _school(client, admin_headers)
    _, _, crew = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 600, 660)
    _solve(client, admin_headers)
    on_trip = _driver(client, admin_headers, "On Trip")
    trip = _trip(client, admin_headers, "09:00", "13:30")
    assert _assign(client, admin_headers, trip, driver=on_trip).status_code == 200

    response = client.patch(
        f"/crews/{crew['id']}", headers=admin_headers, json={"driver_id": on_trip["id"]}
    )
    assert response.status_code == 409
    assert f"on field trip #{trip['id']}" in response.json()["detail"]
