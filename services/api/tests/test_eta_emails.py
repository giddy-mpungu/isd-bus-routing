"""Emailing families when their child's bus time changes (Phase 5.5)."""

import re
from datetime import UTC, datetime

import pytest

from isd_api import eta_notifications, mailer, worker
from isd_api.config import settings
from isd_api.models import Assignment, AuditLogEntry, EtaNotification, Role, RouteStop, Stop
from tests.conftest import auth_headers, login, make_user
from tests.test_daily_trip import DAY, _not_riding, _setup
from tests.test_email import FakeSMTP, outbox  # noqa: F401  (fixture)

# District time is US Central: 11:00 UTC is 06:00 on the morning of DAY.
MORNING = datetime(2026, 10, 5, 11, 0, tzinfo=UTC)


@pytest.fixture()
def day(client, admin_headers, db_session, outbox):  # noqa: F811
    trip = _setup(client, admin_headers, db_session)
    parent = make_user(db_session, email="parent@example.org", role=Role.PARENT, full_name="Pat")
    for name in ("Ana", "Ben"):
        client.post(
            f"/students/{trip['students'][name]['id']}/guardians",
            headers=admin_headers,
            json={"user_id": parent.id},
        )
    trip["parent"] = parent
    return trip


def _shift_plan(db_session, label, minutes):
    """Moves a stop's planned time, so today's estimate differs from it."""
    stop = db_session.query(Stop).filter_by(label=label).one()
    route_stop = db_session.query(RouteStop).filter_by(stop_id=stop.id).one()
    route_stop.minutes_from_start += minutes
    db_session.commit()


def _family(client, parent_email="parent@example.org"):
    headers = auth_headers(login(client, email=parent_email))
    members = client.get(
        "/students/my-family", headers=headers, params={"service_date": DAY}
    ).json()
    return {m["full_name"].split()[0]: m for m in members}


def test_no_email_while_times_match_the_plan(day, db_session, outbox):  # noqa: F811
    assert eta_notifications.run(db_session, MORNING) == 0
    assert outbox == []


def test_a_change_of_ten_minutes_or_more_is_emailed_once(client, day, db_session, outbox):  # noqa: F811
    _shift_plan(db_session, "Far", -15)  # Ana's stop: today's estimate is now 15 later
    ana = _family(client)["Ana"]["am_eta"]

    assert eta_notifications.run(db_session, MORNING) == 1
    (message,) = outbox
    hhmm = f"{ana['eta_minute'] // 60:02d}:{ana['eta_minute'] % 60:02d}"
    planned = f"{ana['planned_minute'] // 60:02d}:{ana['planned_minute'] % 60:02d}"
    assert message["To"] == "parent@example.org"
    assert message["Subject"] == f"Bus time change for Ana: {hhmm}"
    body = message.get_content()
    assert (
        f"morning pickup for Ana at Far is now expected at about {hhmm} (planned {planned})" in body
    )
    assert re.search(r"/email-preferences#token=[\w.-]+", body)

    # Nothing new: no second email.
    assert eta_notifications.run(db_session, MORNING) == 0
    assert db_session.query(EtaNotification).count() == 1


def test_small_changes_are_not_emailed(day, db_session, outbox):  # noqa: F811
    _shift_plan(db_session, "Far", -9)
    assert eta_notifications.run(db_session, MORNING) == 0


def test_another_move_of_ten_minutes_is_emailed_again(client, day, db_session, outbox):  # noqa: F811
    _shift_plan(db_session, "Far", -15)
    assert eta_notifications.run(db_session, MORNING) == 1
    # The bus now starts 15 minutes earlier: today's estimate moves again.
    assignment = db_session.query(Assignment).one()
    assignment.start_minute -= 15
    db_session.commit()
    assert eta_notifications.run(db_session, MORNING) == 1
    assert len(outbox) == 2
    times = sorted(r.eta_minute for r in db_session.query(EtaNotification).all())
    assert times[1] - times[0] == 15


def test_quiet_until_half_past_five_and_never_after_the_bus_has_been(
    day,
    db_session,
    outbox,  # noqa: F811
):
    _shift_plan(db_session, "Far", -15)
    assert (
        eta_notifications.run(db_session, datetime(2026, 10, 5, 10, 29, tzinfo=UTC)) == 0
    )  # 05:29
    assert eta_notifications.run(db_session, datetime(2026, 10, 5, 18, 0, tzinfo=UTC)) == 0  # 13:00
    assert (
        eta_notifications.run(db_session, datetime(2026, 10, 5, 10, 30, tzinfo=UTC)) == 1
    )  # 05:30
    # Another day's runs don't count.
    assert eta_notifications.run(db_session, datetime(2026, 10, 6, 11, 0, tzinfo=UTC)) == 0


def test_who_is_not_emailed(client, day, db_session, outbox, monkeypatch):  # noqa: F811
    _shift_plan(db_session, "Far", -15)
    day["parent"].eta_emails_enabled = False
    db_session.commit()
    assert eta_notifications.run(db_session, MORNING) == 0

    day["parent"].eta_emails_enabled = True
    day["parent"].is_active = False
    db_session.commit()
    assert eta_notifications.run(db_session, MORNING) == 0

    day["parent"].is_active = True
    db_session.commit()
    monkeypatch.setattr(settings, "smtp_host", None)
    assert eta_notifications.run(db_session, MORNING) == 0


def test_a_child_not_riding_today_gets_no_email(client, admin_headers, day, db_session, outbox):  # noqa: F811
    _shift_plan(db_session, "Far", -15)
    _not_riding(client, admin_headers, day["students"]["Ana"])
    assert eta_notifications.run(db_session, MORNING) == 0


def test_a_failed_send_is_retried_next_time(day, db_session, outbox, monkeypatch):  # noqa: F811
    _shift_plan(db_session, "Far", -15)

    def down(self, message):
        raise OSError("mail server down")

    monkeypatch.setattr(FakeSMTP, "send_message", down)
    assert eta_notifications.run(db_session, MORNING) == 0
    assert db_session.query(EtaNotification).count() == 0
    monkeypatch.undo()
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "mail_from", "Bus Office <bus@example.test>")
    assert eta_notifications.run(db_session, MORNING) == 1


def test_the_link_in_the_email_turns_them_off(client, day, db_session, outbox):  # noqa: F811
    _shift_plan(db_session, "Far", -15)
    eta_notifications.run(db_session, MORNING)
    token = re.search(r"#token=([\w.-]+)", outbox[0].get_content()).group(1)

    assert client.post("/notifications/eta/opt-out", json={"token": "nonsense"}).status_code == 400
    assert client.post("/notifications/eta/opt-out", json={"token": token}).status_code == 204
    db_session.refresh(day["parent"])
    assert day["parent"].eta_emails_enabled is False
    assert db_session.query(AuditLogEntry).filter_by(action="eta_emails_off").count() == 1


def test_parents_switch_them_on_and_off(client, day, db_session):
    headers = auth_headers(login(client, email="parent@example.org"))
    assert client.get("/users/me/notification-settings", headers=headers).json() == {
        "eta_emails": True
    }
    off = client.put("/users/me/notification-settings", headers=headers, json={"eta_emails": False})
    assert off.json() == {"eta_emails": False}
    db_session.refresh(day["parent"])
    assert day["parent"].eta_emails_enabled is False

    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    staff = auth_headers(login(client, email="disp@example.org"))
    assert client.get("/users/me/notification-settings", headers=staff).status_code == 403


def test_the_worker_keeps_going_when_a_job_fails(monkeypatch):
    calls = []

    def boom(db):
        calls.append("boom")
        raise RuntimeError("broken")

    def fine(db):
        calls.append("fine")
        return 0

    monkeypatch.setattr(worker, "JOBS", [("boom", boom), ("fine", fine)])
    worker.run_once()
    assert calls == ["boom", "fine"]
