"""Driver license classes (spec sections 1, 2.1, 15): tiered CDL A > CDL B >
Class C (non-CDL), enforced everywhere a driver is paired with a vehicle.
Unknown fails closed."""

import pytest

from isd_api.licensing import infer_required_class, license_class_from_codes, may_drive
from isd_api.models import AuditLogEntry, LicenseClass

A, B, C = LicenseClass.CDL_A, LicenseClass.CDL_B, LicenseClass.CLASS_C
DAY = "2026-10-05"


# --- The rule ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("held", "required", "allowed"),
    [
        (A, A, True), (A, B, True), (A, C, True),
        (B, A, False), (B, B, True), (B, C, True),
        (C, A, False), (C, B, False), (C, C, True),
        (None, C, False),
    ],
)  # fmt: skip
def test_classes_are_tiered_and_unknown_drives_nothing(held, required, allowed):
    assert may_drive(held, required) is allowed


@pytest.mark.parametrize(
    ("nominal", "effective", "expected"),
    [(72, 66, B), (15, None, B), (14, None, C), (None, 12, C), (None, None, B)],
)
def test_vehicle_class_is_inferred_from_passenger_capacity(nominal, effective, expected):
    # 15+ passengers is 16+ people with the driver: a CDL vehicle.
    # Unknown capacity fails closed to needing a CDL.
    assert infer_required_class(nominal, effective) == expected


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (["CDL_B"], B), (["cdl-a"], A), (["NON_CDL_C"], C), (["Class C"], C),
        (["CDL_B", "CDL_A"], A), (["SPED_CERT"], None), ([], None),
    ],
)  # fmt: skip
def test_license_class_is_read_from_existing_license_codes(codes, expected):
    assert license_class_from_codes(codes) == expected


# --- Recording classes -----------------------------------------------------------


def _driver(client, h, name, license_class=None, **extra):
    body = {"full_name": name, **extra}
    if license_class is not None:
        body["license_class"] = license_class
    return client.post("/drivers", headers=h, json=body).json()


def _vehicle(client, h, label, capacity=None, **extra):
    body = {"label": label, **extra}
    if capacity is not None:
        body["nominal_capacity"] = capacity
    return client.post("/vehicles", headers=h, json=body).json()


def _crew(client, h, driver, vehicle, day=DAY):
    return client.post(
        "/crews",
        headers=h,
        json={
            "service_date": day,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 360,
            "available_window_latest": 1000,
        },
    )


def test_a_driver_class_comes_from_the_request_or_their_license_code(client, admin_headers):
    client.post("/qualifications", headers=admin_headers, json={"code": "CDL_B", "kind": "license"})
    assert _driver(client, admin_headers, "Explicit", "cdl_a")["license_class"] == "cdl_a"
    assert (
        _driver(client, admin_headers, "From code", qualification_codes=["CDL_B"])["license_class"]
        == "cdl_b"
    )
    assert _driver(client, admin_headers, "Unknown")["license_class"] is None


def test_a_driver_class_can_be_changed_and_cleared_and_is_audited(
    client, admin_headers, db_session
):
    driver = _driver(client, admin_headers, "Jordan", "class_c")
    upgraded = client.patch(
        f"/drivers/{driver['id']}", headers=admin_headers, json={"license_class": "cdl_b"}
    )
    assert upgraded.json()["license_class"] == "cdl_b"
    untouched = client.patch(
        f"/drivers/{driver['id']}", headers=admin_headers, json={"full_name": "Jordan R."}
    )
    assert untouched.json()["license_class"] == "cdl_b"
    cleared = client.patch(
        f"/drivers/{driver['id']}", headers=admin_headers, json={"license_class": None}
    )
    assert cleared.json()["license_class"] is None

    first = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "driver", AuditLogEntry.entity_id == driver["id"])
        .order_by(AuditLogEntry.id)
        .first()
    )
    assert first.before_state["license_class"] == "class_c"
    assert first.after_state["license_class"] == "cdl_b"


def test_a_vehicle_class_is_inferred_overridable_and_editable(client, admin_headers):
    assert _vehicle(client, admin_headers, "Bus", 72)["required_license_class"] == "cdl_b"
    assert _vehicle(client, admin_headers, "Van", 12)["required_license_class"] == "class_c"
    assert _vehicle(client, admin_headers, "Unknown")["required_license_class"] == "cdl_b"
    tractor = _vehicle(client, admin_headers, "Tractor", 40, required_license_class="cdl_a")
    assert tractor["required_license_class"] == "cdl_a"

    edited = client.patch(
        f"/vehicles/{tractor['id']}",
        headers=admin_headers,
        json={"required_license_class": "cdl_b"},
    )
    assert edited.json()["required_license_class"] == "cdl_b"


# --- Pairing a driver with a vehicle ---------------------------------------------


def test_the_reviews_finding_a_non_cdl_driver_cannot_crew_a_72_seat_bus(client, admin_headers):
    driver = _driver(client, admin_headers, "Van Driver", "class_c")
    bus = _vehicle(client, admin_headers, "Big Bus", 72)
    response = _crew(client, admin_headers, driver, bus)
    assert response.status_code == 400
    assert "isn't licensed for Big Bus, which needs CDL B" in response.json()["detail"]


@pytest.mark.parametrize(
    ("held", "capacity", "status"),
    [("cdl_b", 12, 201), ("cdl_a", 72, 201), ("cdl_b", 72, 201), (None, 12, 400)],
)
def test_crew_creation_follows_the_tiers(client, admin_headers, held, capacity, status):
    driver = _driver(client, admin_headers, "D", held)
    vehicle = _vehicle(client, admin_headers, "V", capacity)
    response = _crew(client, admin_headers, driver, vehicle)
    assert response.status_code == status, response.text
    if status == 400:
        assert "no license class on record" in response.json()["detail"]


def test_repointing_a_crew_to_an_unlicensed_substitute_is_refused(client, admin_headers):
    crew = _crew(
        client,
        admin_headers,
        _driver(client, admin_headers, "Regular", "cdl_b"),
        _vehicle(client, admin_headers, "Bus", 72),
    ).json()
    sub = _driver(client, admin_headers, "Sub", "class_c")
    response = client.patch(
        f"/crews/{crew['id']}", headers=admin_headers, json={"driver_id": sub["id"]}
    )
    assert response.status_code == 409
    assert "isn't licensed" in response.json()["detail"]


# --- The solver and existing crews -----------------------------------------------


def _school(client, h):
    return client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()


def _run(client, h, school, earliest, latest):
    return client.post(
        "/runs",
        headers=h,
        json={
            "service_date": DAY,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": earliest,
            "window_latest": latest,
            "duration_minutes": 30,
        },
    ).json()


def test_a_driver_downgraded_after_the_crew_exists_is_not_scheduled_and_is_flagged(
    client, admin_headers
):
    # Crew A covers both runs alone, the solver's unique best plan. Once A's
    # driver no longer holds a CDL, only B + C remain.
    school = _school(client, admin_headers)
    a_driver = _driver(client, admin_headers, "A", "cdl_b")
    a_crew = _crew(client, admin_headers, a_driver, _vehicle(client, admin_headers, "Bus A", 72))
    b_crew = client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": DAY,
            "driver_id": _driver(client, admin_headers, "B", "cdl_b")["id"],
            "vehicle_id": _vehicle(client, admin_headers, "Bus B", 72)["id"],
            "available_window_earliest": 360,
            "available_window_latest": 500,
        },
    ).json()
    c_crew = client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": DAY,
            "driver_id": _driver(client, admin_headers, "C", "cdl_b")["id"],
            "vehicle_id": _vehicle(client, admin_headers, "Bus C", 72)["id"],
            "available_window_earliest": 560,
            "available_window_latest": 700,
        },
    ).json()
    _run(client, admin_headers, school, 400, 440)
    _run(client, admin_headers, school, 600, 640)
    solved = client.post("/schedule", headers=admin_headers, json={"service_date": DAY}).json()
    assert {a["crew_id"] for a in solved["assignments"]} == {a_crew.json()["id"]}

    # Lock one of A's assignments, then downgrade A's driver.
    locked = solved["assignments"][0]
    client.patch(
        f"/schedule/assignments/{locked['id']}", headers=admin_headers, json={"locked": True}
    )
    client.patch(
        f"/drivers/{a_driver['id']}", headers=admin_headers, json={"license_class": "class_c"}
    )

    resolved = client.post("/schedule", headers=admin_headers, json={"service_date": DAY}).json()
    by_id = {a["id"]: a for a in resolved["assignments"]}
    # The locked one stays (a human override) but is flagged...
    assert by_id[locked["id"]]["crew_id"] == a_crew.json()["id"]
    assert "isn't licensed for Bus A" in by_id[locked["id"]]["availability_issue"]
    # ...and the other run moved off A's crew.
    others = [a for a in resolved["assignments"] if a["id"] != locked["id"]]
    assert {a["crew_id"] for a in others} <= {b_crew["id"], c_crew["id"]}


def test_manual_reassignment_onto_an_unlicensed_crew_is_rejected(client, admin_headers):
    school = _school(client, admin_headers)
    good = _crew(
        client,
        admin_headers,
        _driver(client, admin_headers, "Good", "cdl_b"),
        _vehicle(client, admin_headers, "Bus G", 72),
    ).json()
    weak_driver = _driver(client, admin_headers, "Weak", "cdl_b")
    weak = _crew(
        client, admin_headers, weak_driver, _vehicle(client, admin_headers, "Bus W", 72)
    ).json()
    _run(client, admin_headers, school, 420, 480)
    [assignment] = client.post(
        "/schedule", headers=admin_headers, json={"service_date": DAY}
    ).json()["assignments"]
    target = weak if assignment["crew_id"] == good["id"] else good
    if target is good:
        # Make sure the *target* is the unlicensed one.
        client.patch(
            f"/schedule/assignments/{assignment['id']}",
            headers=admin_headers,
            json={"crew_id": good["id"]},
        )
        target = weak
    client.patch(
        f"/drivers/{weak_driver['id']}", headers=admin_headers, json={"license_class": "class_c"}
    )

    response = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"crew_id": target["id"]},
    )
    assert response.status_code == 422
    assert "isn't licensed" in response.json()["detail"]


# --- Templates, substitutes, field trips ------------------------------------------


def _crew_template(client, h, driver, vehicle):
    return client.post(
        "/crew-templates",
        headers=h,
        json={
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 360,
            "available_window_latest": 1000,
            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
        },
    )


def test_crew_templates_refuse_unlicensed_pairings_and_generation_skips_later_ones(
    client, admin_headers
):
    bus = _vehicle(client, admin_headers, "Bus", 72)
    refused = _crew_template(
        client, admin_headers, _driver(client, admin_headers, "C", "class_c"), bus
    )
    assert refused.status_code == 400

    driver = _driver(client, admin_headers, "B", "cdl_b")
    template = _crew_template(client, admin_headers, driver, bus).json()
    client.patch(
        f"/drivers/{driver['id']}", headers=admin_headers, json={"license_class": "class_c"}
    )
    result = client.post(f"/schedule/{DAY}/generate-from-templates", headers=admin_headers).json()
    assert result["crews_created"] == 0
    assert result["crews_skipped_unlicensed_template_ids"] == [template["id"]]


def test_substitutes_must_be_licensed_for_the_bus_they_would_drive(client, admin_headers):
    school = _school(client, admin_headers)
    absent = _driver(client, admin_headers, "Absent", "cdl_b")
    _crew(client, admin_headers, absent, _vehicle(client, admin_headers, "Bus", 72))
    _run(client, admin_headers, school, 420, 480)
    client.post("/schedule", headers=admin_headers, json={"service_date": DAY})
    licensed = _driver(client, admin_headers, "Licensed Sub", "cdl_b")
    unlicensed = _driver(client, admin_headers, "Van-only Sub", "class_c")

    [affected] = client.get(
        f"/drivers/{absent['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": DAY},
    ).json()
    ids = {c["driver_id"] for c in affected["candidates"]}
    assert licensed["id"] in ids
    assert unlicensed["id"] not in ids


def test_field_trips_refuse_an_unlicensed_driver_for_the_chosen_bus(client, admin_headers):
    trip = client.post(
        "/field-trips",
        headers=admin_headers,
        json={
            "requesting_party": "Choir",
            "origin": "School",
            "destination": "Festival",
            "departure_at": f"{DAY}T09:00:00",
            "expected_return_at": f"{DAY}T13:00:00",
            # Small enough for the van, so only the license decides.
            "passenger_count": 10,
            "trip_contact": "Mr. Reyes",
        },
    ).json()
    van_driver = _driver(client, admin_headers, "Van Driver", "class_c")
    bus, van = (
        _vehicle(client, admin_headers, "Bus", 72),
        _vehicle(client, admin_headers, "Van", 12),
    )

    refused = client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"assigned_driver_id": van_driver["id"], "assigned_vehicle_id": bus["id"]},
    )
    assert refused.status_code == 409
    assert "isn't licensed for Bus" in refused.json()["detail"]

    ok = client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"assigned_driver_id": van_driver["id"], "assigned_vehicle_id": van["id"]},
    )
    assert ok.status_code == 200, ok.text
