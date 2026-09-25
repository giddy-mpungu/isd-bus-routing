"""The assignment lifecycle (spec section 14): Sent -> Received ->
Acknowledged -> En Route -> Arrived -> In Progress -> Completed, plus
No-show. Drivers only move forward; dispatch can correct; a new driver has
to receive and acknowledge again."""

import pytest

from isd_api.assignment_states import driver_transition_problem
from isd_api.models import AssignmentStatus, AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user

DAY = "2026-10-05"
S = AssignmentStatus


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (S.SENT, S.RECEIVED, True),
        (S.RECEIVED, S.ACKNOWLEDGED, True),
        (S.ACKNOWLEDGED, S.IN_PROGRESS, True),  # skipping ahead is fine
        (S.IN_PROGRESS, S.COMPLETED, True),
        (S.ACKNOWLEDGED, S.NO_SHOW, True),
        (S.IN_PROGRESS, S.ACKNOWLEDGED, False),  # never backwards
        (S.RECEIVED, S.SENT, False),  # only dispatch re-sends
        (S.COMPLETED, S.IN_PROGRESS, False),  # finished is finished
        (S.NO_SHOW, S.COMPLETED, False),
        (S.ARRIVED, S.ARRIVED, True),  # repeating a tap is harmless
    ],
)
def test_driver_transitions(current, target, allowed):
    assert (driver_transition_problem(current, target) is None) is allowed


def _day(client, h, db_session, *, drivers=("A",)):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    crews, logins = [], []
    for label in drivers:
        driver = client.post(
            "/drivers", headers=h, json={"full_name": f"Driver {label}", "license_class": "cdl_b"}
        ).json()
        vehicle = client.post(
            "/vehicles", headers=h, json={"label": f"Bus {label}", "nominal_capacity": 48}
        ).json()
        crews.append(
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
            ).json()
        )
        email = f"driver.{label.lower()}@example.org"
        make_user(db_session, email=email, role=Role.DRIVER, driver_id=driver["id"])
        logins.append(auth_headers(login(client, email=email)))
    client.post(
        "/runs",
        headers=h,
        json={
            "service_date": DAY,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 420,
            "window_latest": 480,
            "duration_minutes": 30,
        },
    )
    [assignment] = client.post("/schedule", headers=h, json={"service_date": DAY}).json()[
        "assignments"
    ]
    return assignment, crews, logins


def _set(client, h, assignment, target):
    return client.patch(
        f"/schedule/assignments/{assignment['id']}/status", headers=h, json={"status": target}
    )


def _status_audits(db_session, assignment):
    return (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "assignment",
            AuditLogEntry.entity_id == assignment["id"],
            AuditLogEntry.action == "status_changed",
        )
        .order_by(AuditLogEntry.id)
        .all()
    )


def _driver_of(assignment, crews, logins):
    return logins[[c["id"] for c in crews].index(assignment["crew_id"])]


def test_a_new_assignment_is_sent_and_dispatch_can_see_its_state(client, admin_headers, db_session):
    assignment, _, _ = _day(client, admin_headers, db_session)
    assert assignment["status"] == "sent"
    [listed] = client.get(f"/schedule/{DAY}/assignments", headers=admin_headers).json()
    assert listed["status"] == "sent"


def test_the_drivers_tablet_marks_its_assignments_received_once(client, admin_headers, db_session):
    assignment, crews, logins = _day(client, admin_headers, db_session)
    driver = _driver_of(assignment, crews, logins)

    first = client.post(f"/schedule/{DAY}/my-assignments/receipt", headers=driver)
    assert first.status_code == 200
    assert [a["status"] for a in first.json()] == ["received"]
    again = client.post(f"/schedule/{DAY}/my-assignments/receipt", headers=driver)
    assert [a["status"] for a in again.json()] == ["received"]

    audits = _status_audits(db_session, assignment)
    assert [(e.before_state["status"], e.after_state["status"]) for e in audits] == [
        ("sent", "received")
    ]


def test_receipt_only_touches_the_drivers_own_assignments(client, admin_headers, db_session):
    assignment, crews, logins = _day(client, admin_headers, db_session, drivers=("A", "B"))
    other = logins[1 - [c["id"] for c in crews].index(assignment["crew_id"])]
    assert client.post(f"/schedule/{DAY}/my-assignments/receipt", headers=other).json() == []
    [listed] = client.get(f"/schedule/{DAY}/assignments", headers=admin_headers).json()
    assert listed["status"] == "sent"


def test_a_driver_walks_the_lifecycle_forward(client, admin_headers, db_session):
    assignment, crews, logins = _day(client, admin_headers, db_session)
    driver = _driver_of(assignment, crews, logins)
    for target in ("received", "acknowledged", "en_route", "arrived", "in_progress", "completed"):
        response = _set(client, driver, assignment, target)
        assert response.status_code == 200, (target, response.text)
        assert response.json()["status"] == target

    refused = _set(client, driver, assignment, "in_progress")
    assert refused.status_code == 409
    assert "already completed" in refused.json()["detail"]


def test_going_backwards_is_refused_and_a_repeat_tap_writes_nothing(
    client, admin_headers, db_session
):
    assignment, crews, logins = _day(client, admin_headers, db_session)
    driver = _driver_of(assignment, crews, logins)
    _set(client, driver, assignment, "in_progress")

    back = _set(client, driver, assignment, "acknowledged")
    assert back.status_code == 409
    assert "Ask dispatch to correct it" in back.json()["detail"]

    before = len(_status_audits(db_session, assignment))
    assert _set(client, driver, assignment, "in_progress").status_code == 200
    assert len(_status_audits(db_session, assignment)) == before


def test_dispatch_can_correct_a_state_and_it_is_audited(client, admin_headers, db_session):
    assignment, crews, logins = _day(client, admin_headers, db_session)
    driver = _driver_of(assignment, crews, logins)
    _set(client, driver, assignment, "completed")

    corrected = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"status": "in_progress"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["status"] == "in_progress"
    entry = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_id == assignment["id"], AuditLogEntry.action == "updated")
        .order_by(AuditLogEntry.id.desc())
        .first()
    )
    assert entry.before_state["status"] == "completed"
    assert entry.after_state["status"] == "in_progress"


def test_handing_an_unstarted_assignment_to_another_driver_sends_it_again(
    client, admin_headers, db_session
):
    assignment, crews, logins = _day(client, admin_headers, db_session, drivers=("A", "B"))
    _set(client, _driver_of(assignment, crews, logins), assignment, "acknowledged")
    other_crew = next(c for c in crews if c["id"] != assignment["crew_id"])

    moved = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"crew_id": other_crew["id"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "sent"


def test_a_crew_repoint_sends_the_crews_work_again(client, admin_headers, db_session):
    assignment, crews, logins = _day(client, admin_headers, db_session)
    _set(client, logins[0], assignment, "acknowledged")
    substitute = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Sub", "license_class": "cdl_b"}
    ).json()
    client.patch(
        f"/crews/{crews[0]['id']}", headers=admin_headers, json={"driver_id": substitute["id"]}
    )
    [listed] = client.get(f"/schedule/{DAY}/assignments", headers=admin_headers).json()
    assert listed["status"] == "sent"


def test_an_assignment_already_underway_keeps_its_state_when_handed_over(
    client, admin_headers, db_session
):
    # A mid-route hand-over (e.g. a breakdown) shouldn't pretend the run
    # hasn't started.
    assignment, crews, logins = _day(client, admin_headers, db_session)
    _set(client, logins[0], assignment, "in_progress")
    substitute = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Sub", "license_class": "cdl_b"}
    ).json()
    client.patch(
        f"/crews/{crews[0]['id']}", headers=admin_headers, json={"driver_id": substitute["id"]}
    )
    [listed] = client.get(f"/schedule/{DAY}/assignments", headers=admin_headers).json()
    assert listed["status"] == "in_progress"


def test_a_driver_cannot_move_someone_elses_assignment(client, admin_headers, db_session):
    assignment, crews, logins = _day(client, admin_headers, db_session, drivers=("A", "B"))
    other = logins[1 - [c["id"] for c in crews].index(assignment["crew_id"])]
    assert _set(client, other, assignment, "acknowledged").status_code == 403
