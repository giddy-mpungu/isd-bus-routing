"""FERPA: who viewed a student, and a family's download of the records."""

from isd_api.models import AuditLogEntry, Role, StudentAccess
from tests.conftest import auth_headers, login, make_user
from tests.test_daily_trip import DAY, _not_riding, _setup


def _school_and_student(client, h, name="Ana Lopez"):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    student = client.post(
        "/students", headers=h, json={"full_name": name, "school_id": school["id"]}
    ).json()
    return school, student


def _views(db_session, **where):
    db_session.expire_all()
    return db_session.query(StudentAccess).filter_by(**where).all()


def _as(client, db_session, email, role, **kwargs):
    user = make_user(db_session, email=email, role=role, **kwargs)
    return user, auth_headers(login(client, email=email))


def test_staff_views_are_logged_once_a_day(client, admin_headers, db_session):
    _, student = _school_and_student(client, admin_headers)
    disp, h = _as(client, db_session, "disp@example.org", Role.DISPATCHER)
    client.get("/students", headers=h)
    client.get("/students", headers=h)
    (row,) = _views(db_session, user_id=disp.id)
    assert (row.student_id, row.what) == (student["id"], "list")


def test_homes_and_guardians_are_logged(client, admin_headers, db_session):
    _, student = _school_and_student(client, admin_headers)
    client.put(
        f"/students/{student['id']}/home",
        headers=admin_headers,
        json={
            "address": "1100 Congress Ave, Austin, TX",
            "location_lat": 30.27,
            "location_lon": -97.74,
        },
    )
    client.get(f"/students/{student['id']}/home", headers=admin_headers)
    client.get(f"/students/{student['id']}/guardians", headers=admin_headers)
    assert {v.what for v in _views(db_session, student_id=student["id"])} == {"home", "guardians"}


def test_a_drivers_roster_and_expected_riders_are_logged(client, admin_headers, db_session):
    day = _setup(client, admin_headers, db_session)
    _not_riding(client, admin_headers, day["students"]["Ben"])
    client.get(f"/schedule/{DAY}/my-assignments", headers=day["driver"])
    rostered = {v.student_id for v in _views(db_session, what="roster")}
    assert rostered == {day["students"]["Ana"]["id"], day["students"]["Cy"]["id"]}  # not Ben

    [run] = client.get("/runs", headers=admin_headers, params={"service_date": DAY}).json()
    client.get(f"/runs/{run['id']}/expected-riders", headers=admin_headers)
    assert len(_views(db_session, what="riders")) == 2


def test_families_looking_at_their_own_children_are_not_staff_views(
    client, admin_headers, db_session
):
    _, student = _school_and_student(client, admin_headers)
    parent, h = _as(client, db_session, "pat@example.org", Role.PARENT)
    client.post(
        f"/students/{student['id']}/guardians", headers=admin_headers, json={"user_id": parent.id}
    )
    client.get("/students/my-family", headers=h, params={"service_date": DAY})
    assert _views(db_session, user_id=parent.id) == []


def test_admins_see_who_viewed_a_student(client, admin_headers, db_session):
    _, student = _school_and_student(client, admin_headers)
    disp, h = _as(
        client, db_session, "disp@example.org", Role.DISPATCHER, full_name="Dana Dispatcher"
    )
    client.get("/students", headers=h)
    rows = client.get(f"/students/{student['id']}/access-log", headers=admin_headers).json()
    assert rows[0]["user_name"] == "Dana Dispatcher"
    assert rows[0]["user_role"] == "dispatcher"
    assert rows[0]["what_label"] == "the student list"
    assert client.get(f"/students/{student['id']}/access-log", headers=h).status_code == 403


def test_a_parent_downloads_everything_held_about_their_child(client, admin_headers, db_session):
    _, student = _school_and_student(client, admin_headers, name="Ana <b>Lopez</b>")
    parent, h = _as(client, db_session, "pat@example.org", Role.PARENT, full_name="Pat Parent")
    sid = student["id"]
    client.post(f"/students/{sid}/guardians", headers=admin_headers, json={"user_id": parent.id})
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

    response = client.get(f"/students/{sid}/records", headers=h)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "no-store"
    page = response.text
    assert "Ana &lt;b&gt;Lopez&lt;/b&gt;" in page and "<b>Lopez" not in page  # escaped
    assert "1100 Congress Ave, Austin, TX" in page
    assert "Pat Parent" in page
    assert "the home address" in page  # who viewed it
    assert "<script" not in page
    entry = db_session.query(AuditLogEntry).filter_by(action="records_downloaded").one()
    assert entry.actor_user_id == parent.id and entry.entity_id == sid


def test_only_that_family_or_an_admin_can_download(client, admin_headers, db_session):
    _, student = _school_and_student(client, admin_headers)
    sid = student["id"]
    _, other = _as(client, db_session, "other@example.org", Role.PARENT)
    assert client.get(f"/students/{sid}/records", headers=other).status_code == 404
    _, disp = _as(client, db_session, "disp@example.org", Role.DISPATCHER)
    assert client.get(f"/students/{sid}/records", headers=disp).status_code == 403
    _, me = _as(client, db_session, "ana@example.org", Role.STUDENT, student_id=sid)
    assert client.get(f"/students/{sid}/records", headers=me).status_code == 200

    assert client.get(f"/students/{sid}/records", headers=admin_headers).status_code == 200
    assert {v.what for v in _views(db_session, student_id=sid)} == {"records"}
