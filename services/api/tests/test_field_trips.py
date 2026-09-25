"""spec section 12: field trips. Conflict detection (12.1) is checked
against regular-route Assignments and other FieldTrips only -- this
system has no Training/Maintenance entity to check against (see
routers/field_trips.py's module docstring)."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def _seed_regular_route(client, admin_headers, *, service_date="2026-09-01"):
    """One school, one driver+vehicle+crew, one scheduled regular
    route -- for exercising field-trip conflict detection against it."""
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Riverside Elementary", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Jordan Driver"},
    ).json()
    vehicle = client.post(
        "/vehicles",
        headers=admin_headers,
        json={"label": "Bus 101", "nominal_capacity": 48, "effective_capacity": 44},
    ).json()
    crew = client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": service_date,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    ).json()
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": service_date,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 420,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    )
    client.post("/schedule", headers=admin_headers, json={"service_date": service_date})
    return driver, vehicle, crew


def _trip_payload(**overrides):
    payload = {
        "requesting_party": "Science Department",
        "origin": "Riverside Elementary",
        "destination": "State Science Museum",
        "departure_at": "2026-09-01T13:00:00Z",
        "expected_return_at": "2026-09-01T16:00:00Z",
        "passenger_count": 30,
        "trip_contact": "Ms. Rivera, 555-0100",
    }
    payload.update(overrides)
    return payload


def test_create_field_trip_round_trips_and_defaults_to_requested(client, admin_headers):
    response = client.post("/field-trips", headers=admin_headers, json=_trip_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "requested"
    assert body["requesting_party"] == "Science Department"
    assert body["assigned_driver_id"] is None

    listed = client.get("/field-trips", headers=admin_headers).json()
    created = next(t for t in listed if t["id"] == body["id"])
    assert created["destination"] == "State Science Museum"


def test_create_field_trip_accepts_an_overnight_trip(client, admin_headers):
    response = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            departure_at="2026-09-01T13:00:00Z", expected_return_at="2026-09-02T08:00:00Z"
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["departure_at"].startswith("2026-09-01")
    assert body["expected_return_at"].startswith("2026-09-02")


def test_create_field_trip_rejects_departure_after_return(client, admin_headers):
    response = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            departure_at="2026-09-01T16:00:00Z", expected_return_at="2026-09-01T13:00:00Z"
        ),
    )
    assert response.status_code == 400
    assert "before" in response.json()["detail"]


def test_create_field_trip_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.post("/field-trips", headers=auth_headers(token), json=_trip_payload())
    assert response.status_code == 403


def test_list_field_trips_filters_by_departure_date(client, admin_headers):
    client.post("/field-trips", headers=admin_headers, json=_trip_payload())
    client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            departure_at="2026-09-05T13:00:00Z", expected_return_at="2026-09-05T16:00:00Z"
        ),
    )

    response = client.get(
        "/field-trips", headers=admin_headers, params={"departure_date": "2026-09-01"}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["departure_at"].startswith("2026-09-01")


def test_update_field_trip_assigns_driver_and_audits(client, admin_headers, db_session):
    trip = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Sam Substitute"},
    ).json()
    vehicle = client.post("/vehicles", headers=admin_headers, json={"label": "Bus 202"}).json()

    response = client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={
            "status": "assigned",
            "assigned_driver_id": driver["id"],
            "assigned_vehicle_id": vehicle["id"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "assigned"
    assert body["assigned_driver_id"] == driver["id"]
    assert body["assigned_vehicle_id"] == vehicle["id"]

    entries = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "field_trip", AuditLogEntry.action == "updated")
        .all()
    )
    assert len(entries) == 1
    assert entries[0].before_state["assigned_driver_id"] is None
    assert entries[0].after_state["assigned_driver_id"] == driver["id"]


def test_update_field_trip_rejects_unknown_driver(client, admin_headers):
    trip = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()
    response = client.patch(
        f"/field-trips/{trip['id']}", headers=admin_headers, json={"assigned_driver_id": 999}
    )
    assert response.status_code == 400


def test_update_field_trip_rejects_unknown_trip(client, admin_headers):
    response = client.patch("/field-trips/999", headers=admin_headers, json={"status": "approved"})
    assert response.status_code == 404


def test_update_field_trip_allows_extending_expected_return_to_a_later_date(client, admin_headers):
    trip = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()
    response = client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"expected_return_at": "2026-09-02T08:00:00Z"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["expected_return_at"].startswith("2026-09-02")


def test_update_field_trip_rejects_expected_return_before_departure(client, admin_headers):
    trip = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()
    response = client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"expected_return_at": "2026-09-01T12:00:00Z"},
    )
    assert response.status_code == 400
    assert "after departure_at" in response.json()["detail"]


def test_create_field_trip_with_a_destination_profile(client, admin_headers):
    profile = client.post(
        "/destination-profiles",
        headers=admin_headers,
        json={"name": "State Science Museum", "approved_entrance": "North doors, Bus Lane 3"},
    ).json()
    response = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(destination_profile_id=profile["id"]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["destination_profile_id"] == profile["id"]
    assert body["destination_profile"]["approved_entrance"] == "North doors, Bus Lane 3"


def test_create_field_trip_rejects_unknown_destination_profile(client, admin_headers):
    response = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(destination_profile_id=999),
    )
    assert response.status_code == 400


def test_update_field_trip_rejects_unknown_destination_profile(client, admin_headers):
    trip = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()
    response = client.patch(
        f"/field-trips/{trip['id']}", headers=admin_headers, json={"destination_profile_id": 999}
    )
    assert response.status_code == 400


def test_conflicts_empty_when_no_overlap(client, admin_headers):
    driver, vehicle, _crew = _seed_regular_route(client, admin_headers)
    trip = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()

    response = client.get(
        f"/field-trips/{trip['id']}/conflicts",
        headers=admin_headers,
        params={"driver_id": driver["id"], "vehicle_id": vehicle["id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["conflicts"] == []


def test_conflicts_detects_overlapping_regular_route(client, admin_headers):
    # Regular route runs 06:00-06:50 (window_earliest=360); field trip
    # departs 06:30, inside that window -- must conflict.
    driver, vehicle, _crew = _seed_regular_route(client, admin_headers)
    trip = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            departure_at="2026-09-01T06:30:00Z", expected_return_at="2026-09-01T09:00:00Z"
        ),
    ).json()

    response = client.get(
        f"/field-trips/{trip['id']}/conflicts",
        headers=admin_headers,
        params={"driver_id": driver["id"], "vehicle_id": vehicle["id"]},
    )
    assert response.status_code == 200, response.text
    conflicts = response.json()["conflicts"]
    assert len(conflicts) == 1
    assert "Regular route" in conflicts[0]


def test_conflicts_detects_overlapping_other_field_trip(client, admin_headers):
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Jordan Driver"},
    ).json()
    first = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()
    client.patch(
        f"/field-trips/{first['id']}",
        headers=admin_headers,
        json={"assigned_driver_id": driver["id"]},
    )
    second = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            requesting_party="Athletics",
            destination="Away Game",
            departure_at="2026-09-01T14:00:00Z",
            expected_return_at="2026-09-01T18:00:00Z",
        ),
    ).json()

    response = client.get(
        f"/field-trips/{second['id']}/conflicts",
        headers=admin_headers,
        params={"driver_id": driver["id"]},
    )
    assert response.status_code == 200, response.text
    conflicts = response.json()["conflicts"]
    assert len(conflicts) == 1
    assert f"Field trip #{first['id']}" in conflicts[0]


def test_conflicts_ignores_a_completed_field_trip(client, admin_headers):
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Jordan Driver"},
    ).json()
    first = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()
    client.patch(
        f"/field-trips/{first['id']}",
        headers=admin_headers,
        json={"assigned_driver_id": driver["id"], "status": "completed"},
    )
    second = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(destination="Away Game"),
    ).json()

    response = client.get(
        f"/field-trips/{second['id']}/conflicts",
        headers=admin_headers,
        params={"driver_id": driver["id"]},
    )
    assert response.json()["conflicts"] == []


def test_conflicts_defaults_to_the_trips_own_assigned_driver_and_vehicle(client, admin_headers):
    driver, vehicle, _crew = _seed_regular_route(client, admin_headers)
    trip = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            departure_at="2026-09-01T06:30:00Z", expected_return_at="2026-09-01T09:00:00Z"
        ),
    ).json()
    client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"assigned_driver_id": driver["id"], "assigned_vehicle_id": vehicle["id"]},
    )

    response = client.get(f"/field-trips/{trip['id']}/conflicts", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert len(response.json()["conflicts"]) == 1


def test_conflicts_detects_overlap_on_the_return_day_of_an_overnight_trip(client, admin_headers):
    # Regular route on 2026-09-02 runs 06:00-06:50 (window_earliest=360).
    # An overnight trip departing 2026-09-01 and returning 2026-09-02 at
    # 08:00 covers all of 2026-09-02 from midnight to 08:00, so it must
    # conflict even though its *departure* day is a day earlier.
    driver, vehicle, _crew = _seed_regular_route(client, admin_headers, service_date="2026-09-02")
    trip = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            departure_at="2026-09-01T13:00:00Z", expected_return_at="2026-09-02T08:00:00Z"
        ),
    ).json()

    response = client.get(
        f"/field-trips/{trip['id']}/conflicts",
        headers=admin_headers,
        params={"driver_id": driver["id"], "vehicle_id": vehicle["id"]},
    )
    assert response.status_code == 200, response.text
    conflicts = response.json()["conflicts"]
    assert len(conflicts) == 1
    assert "Regular route" in conflicts[0]


def test_conflicts_detects_overlap_between_two_overnight_field_trips(client, admin_headers):
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Jordan Driver"},
    ).json()
    first = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            departure_at="2026-09-01T20:00:00Z", expected_return_at="2026-09-02T06:00:00Z"
        ),
    ).json()
    client.patch(
        f"/field-trips/{first['id']}",
        headers=admin_headers,
        json={"assigned_driver_id": driver["id"]},
    )
    # Departs the morning of 2026-09-02, before the first trip's 06:00
    # return -- the two trips' second-day windows overlap.
    second = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            requesting_party="Athletics",
            destination="Away Game",
            departure_at="2026-09-02T05:00:00Z",
            expected_return_at="2026-09-02T09:00:00Z",
        ),
    ).json()

    response = client.get(
        f"/field-trips/{second['id']}/conflicts",
        headers=admin_headers,
        params={"driver_id": driver["id"]},
    )
    assert response.status_code == 200, response.text
    conflicts = response.json()["conflicts"]
    assert len(conflicts) == 1
    assert f"Field trip #{first['id']}" in conflicts[0]


def test_conflicts_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    trip = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()
    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.get(f"/field-trips/{trip['id']}/conflicts", headers=auth_headers(token))
    assert response.status_code == 403


def test_observed_duration_requires_destination_or_profile_id(client, admin_headers):
    response = client.get("/field-trips/observed-duration", headers=admin_headers)
    assert response.status_code == 400


def test_observed_duration_is_empty_with_no_completed_trips(client, admin_headers):
    response = client.get(
        "/field-trips/observed-duration",
        headers=admin_headers,
        params={"destination": "State Science Museum"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "sample_count": 0,
        "average_actual_minutes": None,
        "most_recent_actual_minutes": None,
        "most_recent_departure_date": None,
    }


def test_observed_duration_computes_from_completed_trips_by_destination(client, admin_headers):
    first = client.post("/field-trips", headers=admin_headers, json=_trip_payload()).json()
    client.patch(
        f"/field-trips/{first['id']}",
        headers=admin_headers,
        json={"status": "completed", "actual_return_at": "2026-09-01T15:30:00Z"},
    )
    second = client.post(
        "/field-trips",
        headers=admin_headers,
        json=_trip_payload(
            departure_at="2026-09-08T13:00:00Z", expected_return_at="2026-09-08T16:00:00Z"
        ),
    ).json()
    client.patch(
        f"/field-trips/{second['id']}",
        headers=admin_headers,
        json={"status": "completed", "actual_return_at": "2026-09-08T16:30:00Z"},
    )
    # A trip to a different destination must not be included.
    other = client.post(
        "/field-trips", headers=admin_headers, json=_trip_payload(destination="Away Game")
    ).json()
    client.patch(
        f"/field-trips/{other['id']}",
        headers=admin_headers,
        json={"status": "completed", "actual_return_at": "2026-09-01T14:00:00Z"},
    )

    response = client.get(
        "/field-trips/observed-duration",
        headers=admin_headers,
        params={"destination": "State Science Museum"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sample_count"] == 2
    assert body["average_actual_minutes"] == 180.0  # (150 + 210) / 2
    assert body["most_recent_actual_minutes"] == 210
    assert body["most_recent_departure_date"] == "2026-09-08"


def test_observed_duration_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.get(
        "/field-trips/observed-duration",
        headers=auth_headers(token),
        params={"destination": "State Science Museum"},
    )
    assert response.status_code == 403
