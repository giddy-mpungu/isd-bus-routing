"""Admin editing of students, guardians and schools (spec sections 17, 18,
21 "reassign students"). Guardian links grant access to a child's data,
so linking and unlinking are audited and unlinking really revokes access."""

from isd_api.models import AuditLogEntry, Role, Student, User
from tests.conftest import auth_headers, login, make_user


def _school(client, h, name="Riverside Elementary"):
    return client.post(
        "/schools", headers=h, json={"name": name, "location_lat": 29.7, "location_lon": -95.4}
    ).json()


def _stop(client, h, label="Oak & 5th"):
    return client.post(
        "/stops", headers=h, json={"label": label, "location_lat": 29.71, "location_lon": -95.41}
    ).json()


def _student(client, h, school, stop=None):
    body = {"full_name": "Jamie Student", "school_id": school["id"]}
    if stop:
        body["stop_id"] = stop["id"]
    return client.post("/students", headers=h, json=body).json()


def _audit(db_session, entity_type, entity_id):
    return (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == entity_type, AuditLogEntry.entity_id == entity_id)
        .order_by(AuditLogEntry.id)
        .all()
    )


def _parent(client, db_session, email="parent@example.org"):
    make_user(db_session, email=email, role=Role.PARENT)
    user = db_session.query(User).filter(User.email == email).one()
    return user, auth_headers(login(client, email=email))


# --- Students ----------------------------------------------------------------


def test_admin_can_reassign_a_student_and_it_is_audited(client, admin_headers, db_session):
    school, other_school = _school(client, admin_headers), _school(client, admin_headers, "North")
    stop, other_stop = _stop(client, admin_headers), _stop(client, admin_headers, "Elm & 2nd")
    student = _student(client, admin_headers, school, stop)

    response = client.patch(
        f"/students/{student['id']}",
        headers=admin_headers,
        json={
            "full_name": "Jamie Q. Student",
            "school_id": other_school["id"],
            "stop_id": other_stop["id"],
            "default_ridership": "does_not_ride",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == "Jamie Q. Student"
    assert body["school_id"] == other_school["id"]
    assert body["stop_id"] == other_stop["id"]
    assert body["default_ridership"] == "does_not_ride"

    [entry] = _audit(db_session, "student", student["id"])
    assert entry.action == "updated"
    assert entry.before_state["school_id"] == school["id"]
    assert entry.after_state["school_id"] == other_school["id"]
    assert entry.after_state["default_ridership"] == "does_not_ride"


def test_an_explicit_null_clears_the_stop_and_an_omitted_field_is_left_alone(client, admin_headers):
    school, stop = _school(client, admin_headers), _stop(client, admin_headers)
    student = _student(client, admin_headers, school, stop)

    kept = client.patch(
        f"/students/{student['id']}", headers=admin_headers, json={"default_ridership": "rides"}
    ).json()
    assert kept["stop_id"] == stop["id"]

    cleared = client.patch(
        f"/students/{student['id']}", headers=admin_headers, json={"stop_id": None}
    ).json()
    assert cleared["stop_id"] is None


def test_unknown_school_or_stop_is_rejected(client, admin_headers):
    student = _student(client, admin_headers, _school(client, admin_headers))
    for body in ({"school_id": 99999}, {"stop_id": 99999}, {"school_id": None}):
        response = client.patch(f"/students/{student['id']}", headers=admin_headers, json=body)
        assert response.status_code == 400, body


def test_a_no_op_edit_writes_no_audit_entry(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    student = _student(client, admin_headers, school)
    client.patch(
        f"/students/{student['id']}",
        headers=admin_headers,
        json={"full_name": "Jamie Student", "school_id": school["id"]},
    )
    assert _audit(db_session, "student", student["id"]) == []


def test_sis_owned_fields_cannot_be_changed_locally(client, admin_headers, db_session):
    school, other = _school(client, admin_headers), _school(client, admin_headers, "North")
    stop = _stop(client, admin_headers)
    student = _student(client, admin_headers, school)
    db_session.get(Student, student["id"]).external_id = "sis-123"
    db_session.commit()

    for body in ({"full_name": "Renamed"}, {"school_id": other["id"]}):
        response = client.patch(f"/students/{student['id']}", headers=admin_headers, json=body)
        assert response.status_code == 409, body
        assert "SIS" in response.json()["detail"]

    # Stops and default ridership are local transportation data.
    ok = client.patch(
        f"/students/{student['id']}",
        headers=admin_headers,
        json={"stop_id": stop["id"], "full_name": "Jamie Student"},
    )
    assert ok.status_code == 200, ok.text


def test_only_a_transportation_admin_can_edit_students(client, admin_headers, db_session):
    student = _student(client, admin_headers, _school(client, admin_headers))
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="disp@example.org"))
    response = client.patch(
        f"/students/{student['id']}", headers=dispatcher, json={"full_name": "X"}
    )
    assert response.status_code == 403


# --- Guardians ---------------------------------------------------------------


def test_linking_a_guardian_is_listed_audited_and_grants_access(client, admin_headers, db_session):
    student = _student(client, admin_headers, _school(client, admin_headers))
    parent, parent_headers = _parent(client, db_session)
    assert client.get(f"/students/{student['id']}/guardians", headers=admin_headers).json() == []

    response = client.post(
        f"/students/{student['id']}/guardians", headers=admin_headers, json={"user_id": parent.id}
    )
    assert response.status_code == 204

    assert client.get(f"/students/{student['id']}/guardians", headers=admin_headers).json() == [
        {"user_id": parent.id, "full_name": parent.full_name, "email": parent.email}
    ]
    [entry] = _audit(db_session, "student", student["id"])
    assert entry.action == "guardian_linked"
    assert entry.after_state == {"guardian_user_id": parent.id}

    family = client.get(
        "/students/my-family", headers=parent_headers, params={"service_date": "2026-09-01"}
    ).json()
    assert [s["student_id"] for s in family] == [student["id"]]


def test_linking_the_same_guardian_twice_is_a_no_op(client, admin_headers, db_session):
    student = _student(client, admin_headers, _school(client, admin_headers))
    parent, _ = _parent(client, db_session)
    for _ in range(2):
        client.post(
            f"/students/{student['id']}/guardians",
            headers=admin_headers,
            json={"user_id": parent.id},
        )
    assert (
        len(client.get(f"/students/{student['id']}/guardians", headers=admin_headers).json()) == 1
    )
    assert len(_audit(db_session, "student", student["id"])) == 1


def test_unlinking_a_guardian_revokes_access_and_is_audited(client, admin_headers, db_session):
    student = _student(client, admin_headers, _school(client, admin_headers))
    parent, parent_headers = _parent(client, db_session)
    client.post(
        f"/students/{student['id']}/guardians", headers=admin_headers, json={"user_id": parent.id}
    )

    response = client.delete(
        f"/students/{student['id']}/guardians/{parent.id}", headers=admin_headers
    )
    assert response.status_code == 204
    assert client.get(f"/students/{student['id']}/guardians", headers=admin_headers).json() == []
    entries = _audit(db_session, "student", student["id"])
    assert [e.action for e in entries] == ["guardian_linked", "guardian_unlinked"]
    assert entries[1].before_state == {"guardian_user_id": parent.id}

    # The parent can no longer see or act for the child.
    family = client.get(
        "/students/my-family", headers=parent_headers, params={"service_date": "2026-09-01"}
    ).json()
    assert family == []
    ridership = client.patch(
        f"/students/{student['id']}/ridership",
        headers=parent_headers,
        json={"service_date": "2026-09-01", "direction": "am", "is_riding": False},
    )
    assert ridership.status_code == 403


def test_unlinking_someone_who_is_not_a_guardian_is_a_404(client, admin_headers, db_session):
    student = _student(client, admin_headers, _school(client, admin_headers))
    parent, _ = _parent(client, db_session)
    response = client.delete(
        f"/students/{student['id']}/guardians/{parent.id}", headers=admin_headers
    )
    assert response.status_code == 404


def test_only_a_transportation_admin_can_see_or_change_guardians(client, admin_headers, db_session):
    student = _student(client, admin_headers, _school(client, admin_headers))
    parent, parent_headers = _parent(client, db_session)
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="disp@example.org"))
    for headers in (dispatcher, parent_headers):
        assert (
            client.get(f"/students/{student['id']}/guardians", headers=headers).status_code == 403
        )
        assert (
            client.post(
                f"/students/{student['id']}/guardians",
                headers=headers,
                json={"user_id": parent.id},
            ).status_code
            == 403
        )
        assert (
            client.delete(
                f"/students/{student['id']}/guardians/{parent.id}", headers=headers
            ).status_code
            == 403
        )


# --- Schools -----------------------------------------------------------------


def test_admin_can_rename_and_move_a_school_and_it_is_audited(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    client.patch(f"/schools/{school['id']}", headers=admin_headers, json={"external_id": "org-1"})

    response = client.patch(
        f"/schools/{school['id']}",
        headers=admin_headers,
        json={"name": "Riverside Primary", "location_lat": 29.75, "location_lon": -95.35},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["name"], body["location_lat"], body["location_lon"]) == (
        "Riverside Primary",
        29.75,
        -95.35,
    )
    assert body["external_id"] == "org-1"  # not sent, so untouched

    last = _audit(db_session, "school", school["id"])[-1]
    assert last.before_state["name"] == "Riverside Elementary"
    assert last.after_state["name"] == "Riverside Primary"


def test_school_edits_are_validated(client, admin_headers):
    school = _school(client, admin_headers)
    for body in ({"name": ""}, {"location_lat": 91}, {"location_lon": -181}):
        assert (
            client.patch(f"/schools/{school['id']}", headers=admin_headers, json=body).status_code
            == 422
        ), body
    assert (
        client.patch(
            f"/schools/{school['id']}", headers=admin_headers, json={"name": None}
        ).status_code
        == 400
    )
