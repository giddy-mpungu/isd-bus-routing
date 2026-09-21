"""SIS roster sync via OneRoster users.csv (spec section 19, ADR 0007)."""

from isd_api.models import AuditLogEntry, Role, Student
from tests.conftest import auth_headers, login, make_user

HEADER = "sourcedId,status,role,givenName,familyName,orgSourcedIds\n"


def _csv(*rows: str) -> bytes:
    return (HEADER + "\n".join(rows) + "\n").encode()


def _school(client, headers, name, external_id=None):
    payload = {"name": name, "location_lat": 29.7, "location_lon": -95.4}
    if external_id:
        payload["external_id"] = external_id
    response = client.post("/schools", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _import(client, headers, raw, *, dry_run=True, link_by_name=False):
    return client.post(
        "/integrations/sis/students/import",
        headers=headers,
        files={"file": ("users.csv", raw, "text/csv")},
        data={"dry_run": str(dry_run).lower(), "link_by_name": str(link_by_name).lower()},
    )


def _students(db_session):
    db_session.expire_all()
    return db_session.query(Student).order_by(Student.id).all()


def test_dry_run_reports_creations_without_writing(client, admin_headers, db_session):
    _school(client, admin_headers, "Riverside", "org-a")
    response = _import(
        client,
        admin_headers,
        _csv("s1,active,student,Ana,Lopez,org-a", "s2,active,student,Ben,Ng,org-a"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["counts"]["created"] == 2
    assert [r["action"] for r in body["rows"]] == ["created", "created"]
    assert _students(db_session) == []


def test_apply_creates_students_with_external_ids_and_audits(client, admin_headers, db_session):
    school = _school(client, admin_headers, "Riverside", "org-a")
    response = _import(
        client,
        admin_headers,
        _csv('s1,active,student,Ana,Lopez,"org-a,org-district"'),
        dry_run=False,
    )
    assert response.status_code == 200, response.text
    (student,) = _students(db_session)
    assert (student.full_name, student.school_id, student.external_id) == (
        "Ana Lopez",
        school["id"],
        "s1",
    )
    # Transportation-owned fields keep their defaults, untouched by the SIS.
    assert student.stop_id is None
    assert student.default_ridership.value == "rides"
    entry = db_session.query(AuditLogEntry).filter_by(action="sis_import_created").one()
    assert entry.entity_id == student.id


def test_reimport_is_idempotent_and_updates_only_sis_owned_fields(
    client, admin_headers, db_session
):
    school_a = _school(client, admin_headers, "Riverside", "org-a")
    school_b = _school(client, admin_headers, "Lakeside", "org-b")
    _import(client, admin_headers, _csv("s1,active,student,Ana,Lopez,org-a"), dry_run=False)

    # Transportation staff set ridership locally; the SIS must not clobber it.
    student = _students(db_session)[0]
    student.default_ridership = type(student.default_ridership)("does_not_ride")
    db_session.commit()

    again = _import(
        client, admin_headers, _csv("s1,active,student,Ana,Lopez,org-a"), dry_run=False
    ).json()
    assert again["counts"]["unchanged"] == 1
    assert again["rows"] == []  # unchanged rows are not listed

    moved = _import(
        client, admin_headers, _csv("s1,active,student,Ana Maria,Lopez,org-b"), dry_run=False
    ).json()
    assert moved["counts"]["updated"] == 1
    assert "school" in moved["rows"][0]["detail"] and "name" in moved["rows"][0]["detail"]
    (student,) = _students(db_session)
    assert (student.full_name, student.school_id) == ("Ana Maria Lopez", school_b["id"])
    assert student.default_ridership.value == "does_not_ride"
    assert school_a["id"] != school_b["id"]
    audit = db_session.query(AuditLogEntry).filter_by(action="sis_import_updated").one()
    assert audit.before_state["school_id"] == school_a["id"]
    assert audit.after_state["school_id"] == school_b["id"]


def test_unmapped_school_is_an_error_not_a_guess(client, admin_headers, db_session):
    _school(client, admin_headers, "Riverside", "org-a")
    body = _import(
        client, admin_headers, _csv("s1,active,student,Ana,Lopez,org-unknown"), dry_run=False
    ).json()
    assert body["counts"]["error"] == 1
    assert "mapped to a school" in body["rows"][0]["detail"]
    assert _students(db_session) == []


def test_student_in_two_mapped_schools_is_ambiguous(client, admin_headers, db_session):
    _school(client, admin_headers, "Riverside", "org-a")
    _school(client, admin_headers, "Lakeside", "org-b")
    body = _import(
        client, admin_headers, _csv('s1,active,student,Ana,Lopez,"org-a,org-b"'), dry_run=False
    ).json()
    assert body["counts"]["error"] == 1
    assert "not guessing" in body["rows"][0]["detail"]
    assert _students(db_session) == []


def test_removal_requests_are_reported_never_applied(client, admin_headers, db_session):
    _school(client, admin_headers, "Riverside", "org-a")
    _import(client, admin_headers, _csv("s1,active,student,Ana,Lopez,org-a"), dry_run=False)
    body = _import(
        client, admin_headers, _csv("s1,tobedeleted,student,Ana,Lopez,org-a"), dry_run=False
    ).json()
    assert body["counts"]["removal_requested"] == 1
    assert len(_students(db_session)) == 1


def test_hand_entered_student_needs_review_unless_link_by_name(client, admin_headers, db_session):
    school = _school(client, admin_headers, "Riverside", "org-a")
    manual = client.post(
        "/students",
        headers=admin_headers,
        json={"full_name": "Ana Lopez", "school_id": school["id"]},
    ).json()

    review = _import(
        client, admin_headers, _csv("s1,active,student,Ana,Lopez,org-a"), dry_run=False
    ).json()
    assert review["counts"]["needs_review"] == 1
    assert review["rows"][0]["student_id"] == manual["id"]
    (student,) = _students(db_session)
    assert student.external_id is None  # nothing created or linked without confirmation

    linked = _import(
        client,
        admin_headers,
        _csv("s1,active,student,Ana,Lopez,org-a"),
        dry_run=False,
        link_by_name=True,
    ).json()
    assert linked["counts"]["linked"] == 1
    (student,) = _students(db_session)
    assert (student.id, student.external_id) == (manual["id"], "s1")
    assert db_session.query(AuditLogEntry).filter_by(action="sis_import_linked").count() == 1


def test_two_hand_entered_namesakes_are_never_linked_by_guess(client, admin_headers, db_session):
    school = _school(client, admin_headers, "Riverside", "org-a")
    for _ in range(2):
        client.post(
            "/students",
            headers=admin_headers,
            json={"full_name": "Ana Lopez", "school_id": school["id"]},
        )
    body = _import(
        client,
        admin_headers,
        _csv("s1,active,student,Ana,Lopez,org-a"),
        dry_run=False,
        link_by_name=True,
    ).json()
    assert body["counts"]["needs_review"] == 1
    assert all(s.external_id is None for s in _students(db_session))


def test_dry_run_does_not_double_link_one_student(client, admin_headers):
    school = _school(client, admin_headers, "Riverside", "org-a")
    client.post(
        "/students",
        headers=admin_headers,
        json={"full_name": "Ana Lopez", "school_id": school["id"]},
    )
    body = _import(
        client,
        admin_headers,
        _csv("s1,active,student,Ana,Lopez,org-a", "s2,active,student,Ana,Lopez,org-a"),
        link_by_name=True,
    ).json()
    assert body["counts"]["linked"] == 1
    assert body["counts"]["created"] == 1


def test_bad_file_is_a_400_not_a_crash(client, admin_headers):
    assert _import(client, admin_headers, b"name,grade\nAna,3\n").status_code == 400
    assert _import(client, admin_headers, b"\xff\xfe\x00").status_code == 400


def test_row_level_problems_do_not_block_valid_rows(client, admin_headers, db_session):
    _school(client, admin_headers, "Riverside", "org-a")
    body = _import(
        client,
        admin_headers,
        _csv(
            "s1,active,student,Ana,Lopez,org-a",
            "s1,active,student,Dup,Lopez,org-a",
            "t1,active,teacher,Tia,Ray,org-a",
        ),
        dry_run=False,
    ).json()
    assert body["counts"]["created"] == 1
    assert body["counts"]["error"] == 1
    assert body["ignored_non_student_rows"] == 1
    assert len(_students(db_session)) == 1


def test_only_a_transportation_admin_can_import(client, admin_headers, db_session):
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    make_user(db_session, email="drv@example.org", role=Role.DRIVER)
    raw = _csv("s1,active,student,Ana,Lopez,org-a")
    for email in ("disp@example.org", "drv@example.org"):
        headers = auth_headers(login(client, email=email))
        assert _import(client, headers, raw).status_code == 403
    unauth = client.post(
        "/integrations/sis/students/import",
        files={"file": ("users.csv", raw, "text/csv")},
    )
    assert unauth.status_code in (401, 403)


def test_school_external_id_mapping_is_unique_and_editable(client, admin_headers):
    school_a = _school(client, admin_headers, "Riverside", "org-a")
    school_b = _school(client, admin_headers, "Lakeside")

    clash = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Third", "location_lat": 1, "location_lon": 1, "external_id": "org-a"},
    )
    assert clash.status_code == 409

    set_ok = client.patch(
        f"/schools/{school_b['id']}", headers=admin_headers, json={"external_id": "org-b"}
    )
    assert set_ok.status_code == 200 and set_ok.json()["external_id"] == "org-b"
    clash_patch = client.patch(
        f"/schools/{school_b['id']}", headers=admin_headers, json={"external_id": "org-a"}
    )
    assert clash_patch.status_code == 409
    cleared = client.patch(
        f"/schools/{school_a['id']}", headers=admin_headers, json={"external_id": None}
    )
    assert cleared.status_code == 200 and cleared.json()["external_id"] is None
    assert (
        client.patch("/schools/999", headers=admin_headers, json={"external_id": "x"}).status_code
        == 404
    )


def test_school_mapping_change_requires_admin(client, admin_headers, db_session):
    school = _school(client, admin_headers, "Riverside")
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    headers = auth_headers(login(client, email="disp@example.org"))
    response = client.patch(
        f"/schools/{school['id']}", headers=headers, json={"external_id": "org-a"}
    )
    assert response.status_code == 403
