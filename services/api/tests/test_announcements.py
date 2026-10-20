"""spec sections 9/18: dispatcher-authored notices for drivers and/or
families. Almost always human-authored in this system -- the one
exception is an auto-generated substitution notice, see
routers/announcements.py's module docstring for why."""

from isd_api.models import Announcement, AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user

SERVICE_DATE = "2026-09-01"


def _seed_family(client, admin_headers, *, school_name="Riverside Elementary"):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": school_name, "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    stop = client.post(
        "/stops",
        headers=admin_headers,
        json={"label": "Oak & 5th", "location_lat": 29.71, "location_lon": -95.41},
    ).json()
    student = client.post(
        "/students",
        headers=admin_headers,
        json={
            "full_name": "Jamie Student",
            "school_id": school["id"],
            "stop_id": stop["id"],
            "default_ridership": "rides",
        },
    ).json()
    return school, student


def _link_parent(client, admin_headers, db_session, *, student_id, email):
    make_user(db_session, email=email, role=Role.PARENT)
    from isd_api.models import User

    parent = db_session.query(User).filter(User.email == email).one()
    client.post(
        f"/students/{student_id}/guardians",
        headers=admin_headers,
        json={"user_id": parent.id},
    )
    token = login(client, email=email)
    return auth_headers(token)


def _seed_driver_crew_and_run(
    client,
    admin_headers,
    *,
    label,
    school_id,
    service_date=SERVICE_DATE,
    direction="am",
    window_earliest=360,
    window_latest=410,
    extra_vehicle_qualification_codes=(),
):
    """Deliberately forces eligibility (a unique qualification code) so
    the solver can't merge this run onto some other crew -- same
    precedent as tests/test_absences.py's helper of the same name, and
    for the same reason (avoid a solver tie-break making the crew
    assignment non-deterministic). extra_vehicle_qualification_codes
    lets a test give one crew's vehicle a second run's qualification
    too, so a manual PATCH reassignment between the two runs is
    actually eligible rather than tripping the hard-constraint check."""
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": f"Driver {label}"},
    ).json()
    qualification_code = f"QUAL_{label}"
    client.post(
        "/qualifications",
        headers=admin_headers,
        json={"code": qualification_code, "kind": "vehicle_capability"},
    )
    vehicle = client.post(
        "/vehicles",
        headers=admin_headers,
        json={
            "label": f"Bus {label}",
            # Seats for the family's children, who ride (spec section 15).
            "nominal_capacity": 40,
            "effective_capacity": 40,
            "qualification_codes": [qualification_code, *extra_vehicle_qualification_codes],
        },
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
    run = client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": service_date,
            "school_id": school_id,
            "direction": direction,
            "window_earliest": window_earliest,
            "window_latest": window_latest,
            "duration_minutes": 40,
            "buffer_minutes": 10,
            "required_qualification_codes": [qualification_code],
        },
    ).json()
    return driver, vehicle, crew, run


def test_create_announcement_round_trips_and_defaults_to_general(client, admin_headers):
    response = client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "Buses running 15 minutes late today.", "audience": "family"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["category"] == "general"
    assert body["audience"] == "family"
    assert body["message"] == "Buses running 15 minutes late today."


def test_create_announcement_is_audited(client, admin_headers, db_session):
    response = client.post(
        "/announcements",
        headers=admin_headers,
        json={
            "message": "Route 12 substitute driver today.",
            "category": "substitution",
            "audience": "family",
        },
    )
    announcement_id = response.json()["id"]
    entries = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "announcement", AuditLogEntry.entity_id == announcement_id
        )
        .all()
    )
    assert len(entries) == 1
    assert entries[0].action == "created"
    assert entries[0].after_state["category"] == "substitution"


def test_create_announcement_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER)
    token = login(client, email="driver1@example.org")
    response = client.post(
        "/announcements",
        headers=auth_headers(token),
        json={"message": "Not allowed", "audience": "driver"},
    )
    assert response.status_code == 403


def test_list_announcements_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    make_user(db_session, email="driver2@example.org", role=Role.DRIVER)
    token = login(client, email="driver2@example.org")
    response = client.get("/announcements", headers=auth_headers(token))
    assert response.status_code == 403


def test_list_announcements_returns_newest_first(client, admin_headers):
    client.post(
        "/announcements", headers=admin_headers, json={"message": "First", "audience": "all"}
    )
    client.post(
        "/announcements", headers=admin_headers, json={"message": "Second", "audience": "all"}
    )
    response = client.get("/announcements", headers=admin_headers)
    assert response.status_code == 200, response.text
    messages = [a["message"] for a in response.json()]
    assert messages == ["Second", "First"]


def test_driver_sees_all_and_driver_audience_but_not_family_only(client, admin_headers, db_session):
    client.post(
        "/announcements", headers=admin_headers, json={"message": "For everyone", "audience": "all"}
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For drivers", "audience": "driver"},
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For families", "audience": "family"},
    )

    make_user(db_session, email="driver3@example.org", role=Role.DRIVER)
    token = login(client, email="driver3@example.org")
    response = client.get("/announcements/mine", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    messages = {a["message"] for a in response.json()}
    assert messages == {"For everyone", "For drivers"}


def test_parent_sees_all_and_family_audience_but_not_driver_only(client, admin_headers, db_session):
    client.post(
        "/announcements", headers=admin_headers, json={"message": "For everyone", "audience": "all"}
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For drivers", "audience": "driver"},
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For families", "audience": "family"},
    )

    make_user(db_session, email="parent1@example.org", role=Role.PARENT)
    token = login(client, email="parent1@example.org")
    response = client.get("/announcements/mine", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    messages = {a["message"] for a in response.json()}
    assert messages == {"For everyone", "For families"}


def test_student_sees_family_audience_announcements(client, admin_headers, db_session):
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For families", "audience": "family"},
    )
    make_user(db_session, email="student1@example.org", role=Role.STUDENT)
    token = login(client, email="student1@example.org")
    response = client.get("/announcements/mine", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1


def test_dispatcher_cannot_call_mine_endpoint(client, admin_headers, db_session):
    make_user(db_session, email="dispatcher1@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatcher1@example.org")
    response = client.get("/announcements/mine", headers=auth_headers(token))
    assert response.status_code == 403


def test_family_sees_school_scoped_announcement_for_their_own_school(
    client, admin_headers, db_session
):
    school, student = _seed_family(client, admin_headers)
    parent_headers = _link_parent(
        client, admin_headers, db_session, student_id=student["id"], email="parent_a@example.org"
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "Riverside only", "audience": "family", "school_id": school["id"]},
    )
    response = client.get("/announcements/mine", headers=parent_headers)
    assert response.status_code == 200, response.text
    assert [a["message"] for a in response.json()] == ["Riverside only"]


def test_family_does_not_see_a_different_schools_scoped_announcement(
    client, admin_headers, db_session
):
    _school_a, student_a = _seed_family(client, admin_headers, school_name="School A")
    school_b, _student_b = _seed_family(client, admin_headers, school_name="School B")
    parent_headers = _link_parent(
        client, admin_headers, db_session, student_id=student_a["id"], email="parent_b@example.org"
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "School B only", "audience": "family", "school_id": school_b["id"]},
    )
    response = client.get("/announcements/mine", headers=parent_headers)
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_family_sees_district_wide_announcement_regardless_of_school(
    client, admin_headers, db_session
):
    _school, student = _seed_family(client, admin_headers)
    parent_headers = _link_parent(
        client, admin_headers, db_session, student_id=student["id"], email="parent_c@example.org"
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "District-wide", "audience": "family"},
    )
    response = client.get("/announcements/mine", headers=parent_headers)
    assert response.status_code == 200, response.text
    assert [a["message"] for a in response.json()] == ["District-wide"]


def test_school_admin_sees_their_own_schools_scoped_announcement(client, admin_headers, db_session):
    """spec section 17: school_admin's access list names "transportation
    notices" for their school -- this was a real gap this role had no
    route to at all before now."""
    school, _student = _seed_family(client, admin_headers)
    make_user(
        db_session,
        email="schooladmin_a@example.org",
        role=Role.SCHOOL_ADMIN,
        school_id=school["id"],
    )
    admin_token = login(client, email="schooladmin_a@example.org")
    school_admin_headers = auth_headers(admin_token)

    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "Riverside only", "audience": "family", "school_id": school["id"]},
    )
    response = client.get("/announcements/mine", headers=school_admin_headers)
    assert response.status_code == 200, response.text
    assert [a["message"] for a in response.json()] == ["Riverside only"]


def test_school_admin_does_not_see_a_different_schools_scoped_announcement(
    client, admin_headers, db_session
):
    school_a, _student_a = _seed_family(client, admin_headers, school_name="School A")
    school_b, _student_b = _seed_family(client, admin_headers, school_name="School B")
    make_user(
        db_session,
        email="schooladmin_b@example.org",
        role=Role.SCHOOL_ADMIN,
        school_id=school_a["id"],
    )
    admin_token = login(client, email="schooladmin_b@example.org")
    school_admin_headers = auth_headers(admin_token)

    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "School B only", "audience": "family", "school_id": school_b["id"]},
    )
    response = client.get("/announcements/mine", headers=school_admin_headers)
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_school_admin_sees_district_wide_announcements(client, admin_headers, db_session):
    school, _student = _seed_family(client, admin_headers)
    make_user(
        db_session,
        email="schooladmin_c@example.org",
        role=Role.SCHOOL_ADMIN,
        school_id=school["id"],
    )
    admin_token = login(client, email="schooladmin_c@example.org")
    school_admin_headers = auth_headers(admin_token)

    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "District-wide", "audience": "family"},
    )
    response = client.get("/announcements/mine", headers=school_admin_headers)
    assert response.status_code == 200, response.text
    assert [a["message"] for a in response.json()] == ["District-wide"]


def test_school_admin_with_no_school_id_sees_only_district_wide_announcements(
    client, admin_headers, db_session
):
    school, _student = _seed_family(client, admin_headers)
    make_user(db_session, email="schooladmin_unlinked@example.org", role=Role.SCHOOL_ADMIN)
    admin_token = login(client, email="schooladmin_unlinked@example.org")
    school_admin_headers = auth_headers(admin_token)

    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "Riverside only", "audience": "family", "school_id": school["id"]},
    )
    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "District-wide", "audience": "family"},
    )
    response = client.get("/announcements/mine", headers=school_admin_headers)
    assert response.status_code == 200, response.text
    assert [a["message"] for a in response.json()] == ["District-wide"]


def test_school_admin_does_not_see_driver_only_announcements(client, admin_headers, db_session):
    school, _student = _seed_family(client, admin_headers)
    make_user(
        db_session,
        email="schooladmin_d@example.org",
        role=Role.SCHOOL_ADMIN,
        school_id=school["id"],
    )
    admin_token = login(client, email="schooladmin_d@example.org")
    school_admin_headers = auth_headers(admin_token)

    client.post(
        "/announcements",
        headers=admin_headers,
        json={"message": "For drivers", "audience": "driver"},
    )
    response = client.get("/announcements/mine", headers=school_admin_headers)
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_crew_driver_change_with_no_assignments_yet_creates_no_announcement(client, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Empty Crew School", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    _driver, _vehicle, crew, _run = _seed_driver_crew_and_run(
        client, admin_headers, label="A", school_id=school["id"]
    )
    substitute = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Substitute Driver"},
    ).json()
    response = client.patch(
        f"/crews/{crew['id']}", headers=admin_headers, json={"driver_id": substitute["id"]}
    )
    assert response.status_code == 200, response.text
    assert client.get("/announcements", headers=admin_headers).json() == []


def test_crew_driver_change_on_solved_unambiguous_run_creates_family_substitution_announcement(
    client, admin_headers, db_session
):
    school, student = _seed_family(client, admin_headers)
    parent_headers = _link_parent(
        client, admin_headers, db_session, student_id=student["id"], email="parent_d@example.org"
    )
    _driver, vehicle, crew, _run = _seed_driver_crew_and_run(
        client, admin_headers, label="A", school_id=school["id"]
    )
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text

    substitute = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Substitute Driver"},
    ).json()
    response = client.patch(
        f"/crews/{crew['id']}", headers=admin_headers, json={"driver_id": substitute["id"]}
    )
    assert response.status_code == 200, response.text

    announcements = client.get("/announcements", headers=admin_headers).json()
    assert len(announcements) == 1
    assert announcements[0]["category"] == "substitution"
    assert announcements[0]["audience"] == "family"
    assert announcements[0]["school_id"] == school["id"]
    # Family-facing: the bus to look for, never the driver's identity
    # (spec section 18).
    assert "Substitute Driver" not in announcements[0]["message"]
    assert vehicle["label"] in announcements[0]["message"]
    assert "substitute" in announcements[0]["message"]

    entries = (
        db_session.query(AuditLogEntry).filter(AuditLogEntry.entity_type == "announcement").all()
    )
    assert len(entries) == 1
    assert entries[0].after_state["auto_generated_from_run_id"] is not None

    family_view = client.get("/announcements/mine", headers=parent_headers).json()
    assert len(family_view) == 1
    assert family_view[0]["category"] == "substitution"


def test_crew_driver_change_is_skipped_when_school_date_direction_is_ambiguous(
    client, admin_headers, db_session
):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Ambiguous School", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    _driver_a, _vehicle_a, crew_a, _run_a = _seed_driver_crew_and_run(
        client,
        admin_headers,
        label="A",
        school_id=school["id"],
        window_earliest=360,
        window_latest=410,
    )
    _seed_driver_crew_and_run(
        client,
        admin_headers,
        label="B",
        school_id=school["id"],
        window_earliest=420,
        window_latest=470,
    )
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text

    substitute = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Substitute Driver"},
    ).json()
    response = client.patch(
        f"/crews/{crew_a['id']}", headers=admin_headers, json={"driver_id": substitute["id"]}
    )
    assert response.status_code == 200, response.text
    assert client.get("/announcements", headers=admin_headers).json() == []
    assert db_session.query(Announcement).count() == 0


def test_schedule_reassigning_a_crew_to_a_different_assignment_creates_substitution_announcement(
    client, admin_headers
):
    """Two crews, both equally qualified/available for the one run --
    which crew the solver initially picks is a tie-break we don't care
    about here, only that manually PATCHing the resulting assignment
    to the *other* crew is a genuine, hard-constraint-satisfying crew
    change that should fire the substitution notice."""
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Reassign School", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    client.post(
        "/qualifications",
        headers=admin_headers,
        json={"code": "QUAL_SHARED", "kind": "vehicle_capability"},
    )
    driver_a = client.post(
        "/drivers", headers=admin_headers, json={"license_class": "cdl_a", "full_name": "Driver A"}
    ).json()
    driver_b = client.post(
        "/drivers", headers=admin_headers, json={"license_class": "cdl_a", "full_name": "Driver B"}
    ).json()
    vehicle_a = client.post(
        "/vehicles",
        headers=admin_headers,
        json={"label": "Bus A", "qualification_codes": ["QUAL_SHARED"]},
    ).json()
    vehicle_b = client.post(
        "/vehicles",
        headers=admin_headers,
        json={"label": "Bus B", "qualification_codes": ["QUAL_SHARED"]},
    ).json()
    crew_a = client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": SERVICE_DATE,
            "driver_id": driver_a["id"],
            "vehicle_id": vehicle_a["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    ).json()
    crew_b = client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": SERVICE_DATE,
            "driver_id": driver_b["id"],
            "vehicle_id": vehicle_b["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    ).json()
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": SERVICE_DATE,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 410,
            "duration_minutes": 40,
            "buffer_minutes": 10,
            "required_qualification_codes": ["QUAL_SHARED"],
        },
    )

    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text
    assignment = schedule.json()["assignments"][0]
    other_crew_id = crew_b["id"] if assignment["crew_id"] == crew_a["id"] else crew_a["id"]

    response = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"crew_id": other_crew_id},
    )
    assert response.status_code == 200, response.text

    announcements = client.get("/announcements", headers=admin_headers).json()
    assert len(announcements) == 1
    assert announcements[0]["category"] == "substitution"
    assert announcements[0]["school_id"] == school["id"]


def test_schedule_locking_an_assignment_without_a_crew_change_creates_no_announcement(
    client, admin_headers
):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Lock-Only School", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    _driver, _vehicle, _crew, _run = _seed_driver_crew_and_run(
        client, admin_headers, label="A", school_id=school["id"]
    )
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text
    assignment_id = schedule.json()["assignments"][0]["id"]

    response = client.patch(
        f"/schedule/assignments/{assignment_id}",
        headers=admin_headers,
        json={"locked": True},
    )
    assert response.status_code == 200, response.text
    assert client.get("/announcements", headers=admin_headers).json() == []
