"""Spec section 18's route-change notice: a family is emailed when their
child's bus stop changes, is given, or is taken away."""

from isd_api.models import Role, User
from tests.conftest import make_user
from tests.test_email import FakeSMTP, outbox  # noqa: F401  (fixture)


def _family(client, h, db_session, *, language=None):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    oak, elm = (
        client.post(
            "/stops", headers=h, json={"label": label, "location_lat": 29.71, "location_lon": -95.4}
        ).json()
        for label in ("Oak St", "Elm St")
    )
    mia = client.post(
        "/students",
        headers=h,
        json={"full_name": "Mia Alvarez", "school_id": school["id"], "stop_id": oak["id"]},
    ).json()
    make_user(db_session, email="pat@example.org", role=Role.PARENT, full_name="Pat Alvarez")
    pat = db_session.query(User).filter(User.email == "pat@example.org").one()
    if language:
        pat.preferred_language = language
        db_session.commit()
    client.post(f"/students/{mia['id']}/guardians", headers=h, json={"user_id": pat.id})
    return mia, elm


def test_a_new_stop_is_emailed_to_the_family(client, admin_headers, db_session, outbox):  # noqa: F811
    mia, elm = _family(client, admin_headers, db_session)
    response = client.patch(
        f"/students/{mia['id']}", headers=admin_headers, json={"stop_id": elm["id"]}
    )
    assert response.status_code == 200, response.text
    [message] = outbox
    assert message["To"] == "pat@example.org"
    assert message["Subject"] == "Mia Alvarez's bus stop has changed"
    assert "From now on, Mia Alvarez catches the bus at Elm St." in message.get_content()

    # Nothing else about the student changes the stop: no email.
    client.patch(f"/students/{mia['id']}", headers=admin_headers, json={"grade": "5"})
    assert len(outbox) == 1


def test_a_stop_taken_away_says_to_call_the_office(client, admin_headers, db_session, outbox):  # noqa: F811
    mia, _ = _family(client, admin_headers, db_session)
    client.patch(f"/students/{mia['id']}", headers=admin_headers, json={"stop_id": None})
    [message] = outbox
    assert "doesn't have a bus stop any more" in message.get_content()


def test_the_email_is_in_the_familys_language(client, admin_headers, db_session, outbox):  # noqa: F811
    mia, elm = _family(client, admin_headers, db_session, language="es")
    client.patch(f"/students/{mia['id']}", headers=admin_headers, json={"stop_id": elm["id"]})
    [message] = outbox
    assert message["Subject"] == "La parada de autobús de Mia Alvarez cambió"


def test_without_email_set_up_nothing_is_sent(client, admin_headers, db_session):
    mia, elm = _family(client, admin_headers, db_session)
    FakeSMTP.sent = []
    response = client.patch(
        f"/students/{mia['id']}", headers=admin_headers, json={"stop_id": elm["id"]}
    )
    assert response.status_code == 200
    assert FakeSMTP.sent == []
