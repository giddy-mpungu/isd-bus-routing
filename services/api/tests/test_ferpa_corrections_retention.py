"""FERPA part 2: families asking for corrections, and deleting the data of
students who have left."""

# ruff: noqa: F811  (outbox is a pytest fixture imported from test_email)

from datetime import UTC, date, datetime

import pytest

from isd_api import retention, worker
from isd_api.models import (
    AuditLogEntry,
    RecordCorrection,
    RidershipOverride,
    Role,
    Student,
    StudentAccess,
    StudentHome,
    User,
)
from tests.conftest import auth_headers, login, make_user
from tests.test_daily_trip import DAY, _roster, _setup
from tests.test_email import FakeSMTP, outbox  # noqa: F401  (fixture)


def _family(client, admin_headers, db_session, email="pat@example.org"):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    student = client.post(
        "/students",
        headers=admin_headers,
        json={"full_name": "Ana Lopez", "school_id": school["id"]},
    ).json()
    parent = make_user(db_session, email=email, role=Role.PARENT, full_name="Pat Parent")
    client.post(
        f"/students/{student['id']}/guardians", headers=admin_headers, json={"user_id": parent.id}
    )
    return student, parent, auth_headers(login(client, email=email))


BODY = {"what_is_wrong": "Grade says 4", "should_say": "Grade 5"}


def test_a_family_asks_and_the_office_declines_with_a_reason(
    client, admin_headers, db_session, outbox
):  # noqa: F811
    student, parent, h = _family(client, admin_headers, db_session)
    made = client.post(f"/students/{student['id']}/corrections", headers=h, json=BODY)
    assert made.status_code == 201, made.text
    assert made.json()["status"] == "open"
    assert outbox[-1]["Subject"] == "A family asked for a record correction"
    assert "Ana" not in outbox[-1].get_content()  # admins get a link, not details

    queue = client.get("/corrections", headers=admin_headers).json()
    assert [(c["student_name"], c["requested_by"]) for c in queue] == [("Ana Lopez", "Pat Parent")]
    decided = client.patch(
        f"/corrections/{made.json()['id']}",
        headers=admin_headers,
        json={"decision": "declined", "response": "Grade 4 matches the school's records."},
    )
    assert decided.json()["status"] == "declined"
    body = outbox[-1].get_content()
    assert outbox[-1]["To"] == "pat@example.org"
    assert "Grade 4 matches the school's records." in body and "hearing" in body

    mine = client.get(f"/students/{student['id']}/corrections", headers=h).json()
    assert mine[0]["status"] == "declined" and mine[0]["response"].startswith("Grade 4")
    assert client.get("/corrections", headers=admin_headers).json() == []  # nothing open
    again = client.patch(
        f"/corrections/{made.json()['id']}",
        headers=admin_headers,
        json={"decision": "accepted", "response": "x"},
    )
    assert again.status_code == 409


def test_accepting_says_the_record_was_corrected(client, admin_headers, db_session, outbox):  # noqa: F811
    student, _, h = _family(client, admin_headers, db_session)
    cid = client.post(f"/students/{student['id']}/corrections", headers=h, json=BODY).json()["id"]
    client.patch(
        f"/corrections/{cid}",
        headers=admin_headers,
        json={"decision": "accepted", "response": "Fixed."},
    )
    assert "accepted, and the record has been corrected" in outbox[-1].get_content()
    assert "hearing" not in outbox[-1].get_content()
    assert db_session.query(AuditLogEntry).filter_by(action="correction_accepted").count() == 1


def test_who_can_ask_and_see(client, admin_headers, db_session):
    student, _, _ = _family(client, admin_headers, db_session)
    other = auth_headers(
        login(client, email=make_user(db_session, email="o@example.org", role=Role.PARENT).email)
    )
    assert (
        client.post(f"/students/{student['id']}/corrections", headers=other, json=BODY).status_code
        == 404
    )
    assert client.get(f"/students/{student['id']}/corrections", headers=other).status_code == 404
    disp = auth_headers(
        login(
            client, email=make_user(db_session, email="d@example.org", role=Role.DISPATCHER).email
        )
    )
    assert client.get("/corrections", headers=disp).status_code == 403
    assert (
        client.get(f"/students/{student['id']}/corrections", headers=admin_headers).status_code
        == 200
    )


def test_requests_must_say_something_and_not_flood(client, admin_headers, db_session):
    student, _, h = _family(client, admin_headers, db_session)
    url = f"/students/{student['id']}/corrections"
    assert (
        client.post(url, headers=h, json={"what_is_wrong": "", "should_say": "x"}).status_code
        == 422
    )
    for _ in range(10):
        assert client.post(url, headers=h, json=BODY).status_code == 201
    assert client.post(url, headers=h, json=BODY).status_code == 429


@pytest.mark.parametrize(
    ("withdrawn", "kept_until"),
    [
        (date(2026, 10, 7), date(2028, 6, 30)),
        (date(2027, 6, 30), date(2028, 6, 30)),
        (date(2027, 7, 1), date(2029, 6, 30)),
    ],
)
def test_data_is_kept_through_the_following_school_year(withdrawn, kept_until):
    assert retention.delete_after(withdrawn) == kept_until


def test_withdrawing_and_reinstating(client, admin_headers, db_session):
    student, _, _ = _family(client, admin_headers, db_session)
    out = client.post(
        f"/students/{student['id']}/withdraw",
        headers=admin_headers,
        json={"withdrawn_on": "2026-10-07"},
    )
    assert out.json()["withdrawn_on"] == "2026-10-07" and out.json()["delete_after"] == "2028-06-30"
    back = client.post(f"/students/{student['id']}/reinstate", headers=admin_headers)
    assert back.json()["withdrawn_on"] is None and back.json()["delete_after"] is None
    assert (
        client.post(f"/students/{student['id']}/reinstate", headers=admin_headers).status_code
        == 409
    )
    actions = [e.action for e in db_session.query(AuditLogEntry).filter_by(entity_type="student")]
    assert "withdrawn" in actions and "reinstated" in actions


def test_a_withdrawn_student_stops_riding_from_that_day(client, admin_headers, db_session):
    day = _setup(client, admin_headers, db_session)
    ana = day["students"]["Ana"]
    client.post(
        f"/students/{ana['id']}/withdraw",
        headers=admin_headers,
        json={"withdrawn_on": "2026-10-06"},
    )
    assert "Ana" in _roster(client, day)["Far"]["student_names"]  # DAY is the 5th: still riding
    client.post(
        f"/students/{ana['id']}/withdraw", headers=admin_headers, json={"withdrawn_on": DAY}
    )
    assert _roster(client, day)["Far"]["student_names"] == []


def test_the_data_is_deleted_once_its_time_is_up(client, admin_headers, db_session):
    student, parent, h = _family(client, admin_headers, db_session)
    sid = student["id"]
    client.put(
        f"/students/{sid}/home",
        headers=admin_headers,
        json={
            "address": "1100 Congress Ave, Austin, TX",
            "location_lat": 30.27,
            "location_lon": -97.74,
        },
    )
    client.get(f"/students/{sid}/home", headers=admin_headers)
    client.patch(
        f"/students/{sid}/ridership",
        headers=h,
        json={"service_date": DAY, "direction": "am", "is_riding": False},
    )
    client.post(f"/students/{sid}/corrections", headers=h, json=BODY)
    login_user = make_user(
        db_session, email="ana@kids.example.org", role=Role.STUDENT, student_id=sid
    )
    client.post(
        f"/students/{sid}/withdraw", headers=admin_headers, json={"withdrawn_on": "2026-10-07"}
    )

    assert retention.run(db_session, datetime(2028, 6, 30, 18, tzinfo=UTC)) == 0  # last day kept
    assert retention.run(db_session, datetime(2028, 7, 1, 18, tzinfo=UTC)) == 1
    db_session.expire_all()
    assert db_session.get(Student, sid) is None
    for model in (StudentHome, RidershipOverride, StudentAccess, RecordCorrection):
        assert db_session.query(model).filter(model.student_id == sid).count() == 0
    gone = db_session.get(User, login_user.id)
    assert gone.full_name == "Removed student" and not gone.is_active and gone.student_id is None
    assert gone.email.endswith("@removed.invalid")
    assert db_session.get(User, parent.id).is_active  # the parent's own account stays
    history = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.entity_type.in_(("student", "student_home")), AuditLogEntry.entity_id == sid
    )
    assert all("Ana" not in str(e.before_state) + str(e.after_state) for e in history)
    assert history.filter_by(action="deleted_after_retention").count() == 1


def test_the_worker_runs_retention():
    assert ("FERPA retention", retention.run) in worker.JOBS


def test_the_records_page_lists_correction_requests(client, admin_headers, db_session):
    student, _, h = _family(client, admin_headers, db_session)
    client.post(f"/students/{student['id']}/corrections", headers=h, json=BODY)
    page = client.get(f"/students/{student['id']}/records", headers=h).text
    assert "Correction requests" in page and "Grade says 4" in page
