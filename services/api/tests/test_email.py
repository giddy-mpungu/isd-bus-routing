import logging
import re
from datetime import UTC, datetime, timedelta

import pytest

from isd_api import mailer
from isd_api.config import Settings, settings
from isd_api.models import AuditLogEntry, PasswordResetToken, Role
from tests.conftest import auth_headers, login, make_user

NEW = "yellow-bus-route-7"


class FakeSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL and keeps what was sent."""

    sent: list = []
    calls: list = []

    def __init__(self, host, port, timeout=None, context=None):
        FakeSMTP.calls.append(("connect", host, port, context is not None))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        FakeSMTP.calls.append(("starttls",))

    def login(self, user, password):
        FakeSMTP.calls.append(("login", user, password))

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture()
def outbox(monkeypatch):
    FakeSMTP.sent = []
    FakeSMTP.calls = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_security", "starttls")
    monkeypatch.setattr(settings, "smtp_username", None)
    monkeypatch.setattr(settings, "mail_from", "Bus Office <bus@example.test>")
    monkeypatch.setattr(settings, "public_web_url", "https://bus.example.test/")
    return FakeSMTP.sent


def _token_in(message) -> str:
    match = re.search(
        r"https://bus\.example\.test/reset-password#token=([\w-]+)", message.get_content()
    )
    assert match, message.get_content()
    return match.group(1)


def test_messages_go_over_starttls_with_login(outbox, monkeypatch):
    monkeypatch.setattr(settings, "smtp_username", "apikey")
    monkeypatch.setattr(settings, "smtp_password", "s3cret")
    mailer.send(mailer.Email(to="a@example.org", subject="Hi", body="Hello"))
    assert FakeSMTP.calls == [
        ("connect", "smtp.example.test", 587, False),
        ("starttls",),
        ("login", "apikey", "s3cret"),
    ]
    assert outbox[0]["From"] == "Bus Office <bus@example.test>"
    assert outbox[0]["To"] == "a@example.org"
    assert outbox[0].get_content().strip() == "Hello"


def test_ssl_and_plain_connections(outbox, monkeypatch):
    monkeypatch.setattr(settings, "smtp_security", "ssl")
    monkeypatch.setattr(settings, "smtp_port", 465)
    mailer.send(mailer.Email(to="a@example.org", subject="Hi", body="Hello"))
    assert FakeSMTP.calls == [("connect", "smtp.example.test", 465, True)]

    FakeSMTP.calls.clear()
    monkeypatch.setattr(settings, "smtp_security", "none")
    mailer.send(mailer.Email(to="a@example.org", subject="Hi", body="Hello"))
    assert FakeSMTP.calls == [("connect", "smtp.example.test", 465, False)]


def test_a_failure_is_logged_without_the_message(outbox, monkeypatch):
    def boom(self, message):
        raise OSError("connection refused")

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    mailer.logger.addHandler(handler)
    monkeypatch.setattr(FakeSMTP, "send_message", boom)
    try:
        mailer.send_quietly(mailer.Email(to="a@example.org", subject="Hi", body="secret-link"))
    finally:
        mailer.logger.removeHandler(handler)
    (record,) = records
    assert record.getMessage() == "Couldn't send the 'Hi' email"
    assert "secret-link" not in record.getMessage()


def test_settings_treat_blank_as_unset_and_need_a_sender():
    blank = Settings(smtp_host="", mail_from="", public_web_url="")
    assert blank.smtp_host is None and blank.mail_from is None
    assert blank.web_url == "http://localhost:5173"
    with pytest.raises(RuntimeError, match="ISD_API_MAIL_FROM"):
        Settings(smtp_host="smtp.example.test").require_production_ready()


def test_options_say_whether_email_is_on(client, outbox, monkeypatch):
    assert client.get("/auth/options").json() == {"email_enabled": True}
    monkeypatch.setattr(settings, "smtp_host", None)
    assert client.get("/auth/options").json() == {"email_enabled": False}


def test_forgot_password_emails_a_one_hour_link(client, db_session, outbox):
    user = make_user(db_session, email="Pat@Example.org", role=Role.PARENT, full_name="Pat Parent")
    response = client.post("/auth/forgot-password", json={"email": " pat@example.org "})
    assert response.status_code == 202
    assert response.json()["detail"].startswith("If that email has an account")

    (message,) = outbox
    assert message["To"] == "Pat@Example.org"
    assert message["Subject"] == "Reset your bus app password"
    assert "Hello Pat Parent" in message.get_content()
    assert "within 1 hour" in message.get_content()
    row = db_session.query(PasswordResetToken).one()
    assert row.created_by_user_id is None
    lifetime = row.expires_at.replace(tzinfo=UTC) - row.created_at.replace(tzinfo=UTC)
    assert lifetime == timedelta(hours=1)
    assert (
        db_session.query(AuditLogEntry).filter_by(action="reset_email_sent").one().entity_id
        == user.id
    )

    token = _token_in(message)
    done = client.post("/auth/reset-password", json={"token": token, "new_password": NEW})
    assert done.status_code == 204
    login(client, email="Pat@Example.org", password=NEW)
    # The reset itself sends the password-changed notice.
    assert outbox[-1]["Subject"] == "Your bus app password was changed"


def test_forgot_password_gives_nothing_away(client, db_session, outbox):
    make_user(db_session, email="gone@example.org", role=Role.PARENT, is_active=False)
    known = client.post("/auth/forgot-password", json={"email": "gone@example.org"})
    unknown = client.post("/auth/forgot-password", json={"email": "nobody@example.org"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert outbox == []


def test_forgot_password_limits_emails_per_address(client, db_session, outbox):
    make_user(db_session, email="pat@example.org", role=Role.PARENT)
    codes = [
        client.post("/auth/forgot-password", json={"email": "pat@example.org"}).status_code
        for _ in range(4)
    ]
    assert codes == [202] * 4
    assert len(outbox) == 3


def test_forgot_password_without_email_set_up(client, db_session):
    make_user(db_session, email="pat@example.org", role=Role.PARENT)
    response = client.post("/auth/forgot-password", json={"email": "pat@example.org"})
    assert response.status_code == 503
    assert "Ask your transportation office" in response.json()["detail"]


def test_changing_a_password_sends_a_notice(client, db_session, outbox):
    make_user(db_session, email="pat@example.org", role=Role.DISPATCHER)
    token = login(client, email="pat@example.org")
    response = client.post(
        "/auth/change-password",
        headers=auth_headers(token),
        json={"current_password": "password123", "new_password": NEW},
    )
    assert response.status_code == 200
    (message,) = outbox
    assert message["Subject"] == "Your bus app password was changed"
    assert "If this wasn't you" in message.get_content()


def test_no_notice_when_email_is_off(client, db_session):
    make_user(db_session, email="pat@example.org", role=Role.DISPATCHER)
    token = login(client, email="pat@example.org")
    response = client.post(
        "/auth/change-password",
        headers=auth_headers(token),
        json={"current_password": "password123", "new_password": NEW},
    )
    assert response.status_code == 200


def test_a_new_account_without_a_password_gets_a_setup_email(
    client, admin_headers, db_session, outbox
):
    response = client.post(
        "/users",
        headers=admin_headers,
        json={"email": "new.driver@example.org", "full_name": "New Driver", "role": "driver"},
    )
    assert response.status_code == 201, response.text
    (message,) = outbox
    assert message["Subject"] == "Set up your bus app account"
    assert "within 3 days" in message.get_content()
    assert "https://bus.example.test/login" in message.get_content()
    row = db_session.query(PasswordResetToken).one()
    assert row.expires_at.replace(tzinfo=UTC) - datetime.now(UTC) > timedelta(hours=71)
    entry = db_session.query(AuditLogEntry).filter_by(entity_type="user", action="created").one()
    assert entry.after_state["setup_email"] is True

    # No password works until they choose one.
    refused = client.post(
        "/auth/login", data={"username": "new.driver@example.org", "password": "!unset"}
    )
    assert refused.status_code == 401
    token = _token_in(message)
    assert (
        client.post("/auth/reset-password", json={"token": token, "new_password": NEW}).status_code
        == 204
    )
    login(client, email="new.driver@example.org", password=NEW)


def test_a_passwordless_account_needs_email(client, admin_headers):
    response = client.post(
        "/users",
        headers=admin_headers,
        json={"email": "new@example.org", "full_name": "New", "role": "driver"},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Email isn't set up here, so enter a password for the account"
    )
