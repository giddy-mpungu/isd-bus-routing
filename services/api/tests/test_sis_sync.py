"""The scheduled SIS roster sync from a OneRoster 1.1 REST API."""

import base64
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from isd_api import sis_sync, worker
from isd_api.config import settings
from isd_api.integrations import oneroster_api
from isd_api.models import AuditLogEntry, Role, SisSyncRun, Student
from tests.conftest import auth_headers, login, make_user
from tests.test_email import FakeSMTP, outbox  # noqa: F401  (fixture)
from tests.test_sis_import import _school, _students

BASE = "https://sis.example.test/ims/oneroster/v1p1"
TOKEN_URL = "https://sis.example.test/oauth/token"
# 03:30 in the district (US Central) on 2026-10-06.
NIGHT = datetime(2026, 10, 6, 8, 30, tzinfo=UTC)


def _user(sid, given, family, org="org-a", status="active", grade="05"):
    return {
        "sourcedId": sid,
        "status": status,
        "role": "student",
        "givenName": given,
        "familyName": family,
        "orgs": [{"sourcedId": org, "type": "org"}],
        "grades": [grade],
        # Fields the import must never keep.
        "email": f"{sid}@kids.example.test",
        "phone": "555-0100",
    }


class FakeOneRoster:
    """A district's OneRoster API, as the sync sees it over HTTP."""

    def __init__(self):
        self.users = []
        self.calls = []
        self.fail = None

    def http_json(self, url, *, headers, form=None):
        self.calls.append((url, headers, form))
        if self.fail:
            raise oneroster_api.OneRosterApiError(self.fail)
        if url == TOKEN_URL:
            assert form["grant_type"] == "client_credentials"
            assert (
                headers["Authorization"] == "Basic " + base64.b64encode(b"client:secret").decode()
            )
            return {"access_token": "tok-1", "token_type": "bearer", "expires_in": 3600}
        parts = urlsplit(url)
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{BASE}/students"
        assert headers["Authorization"] == "Bearer tok-1"
        query = parse_qs(parts.query)
        limit, offset = int(query["limit"][0]), int(query["offset"][0])
        return {"users": self.users[offset : offset + limit]}


@pytest.fixture()
def sis(monkeypatch):
    fake = FakeOneRoster()
    monkeypatch.setattr(oneroster_api, "http_json", fake.http_json)
    monkeypatch.setattr(settings, "sis_oneroster_base_url", BASE)
    monkeypatch.setattr(settings, "sis_oneroster_token_url", TOKEN_URL)
    monkeypatch.setattr(settings, "sis_oneroster_client_id", "client")
    monkeypatch.setattr(settings, "sis_oneroster_client_secret", "secret")
    return fake


def test_safe_changes_are_applied_and_the_rest_waits(client, admin_headers, db_session, sis):
    school = _school(client, admin_headers, "Riverside", "org-a")
    client.post(
        "/students",
        headers=admin_headers,
        json={"full_name": "Hand Entered", "school_id": school["id"]},
    )
    sis.users = [
        _user("s1", "Ana", "Lopez"),
        _user("s2", "Hand", "Entered"),  # possible duplicate: never linked by name automatically
        _user("s3", "Gone", "Away", status="tobedeleted"),
        _user("s4", "Other", "School", org="org-unmapped"),
    ]
    response = client.post("/integrations/sis/sync", headers=admin_headers)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["trigger"] == "manual"
    assert run["status"] == "needs_attention"
    assert run["counts"]["created"] == 1
    assert run["counts"]["needs_review"] == 1
    assert run["counts"]["removal_requested"] == 1
    assert run["counts"]["error"] == 1
    assert {p["action"] for p in run["problems"]} == {"needs_review", "removal_requested", "error"}

    names = sorted(s.full_name for s in _students(db_session))
    assert names == ["Ana Lopez", "Hand Entered"]  # no duplicate, nothing removed
    ana = next(s for s in _students(db_session) if s.external_id == "s1")
    assert ana.grade == "5"
    assert db_session.query(AuditLogEntry).filter_by(action="sis_sync_created").count() == 1


def test_a_second_sync_updates_and_reports_nothing_new(client, admin_headers, db_session, sis):
    _school(client, admin_headers, "Riverside", "org-a")
    sis.users = [_user("s1", "Ana", "Lopez")]
    client.post("/integrations/sis/sync", headers=admin_headers)
    sis.users = [_user("s1", "Ana", "Lopez-Garcia")]
    run = client.post("/integrations/sis/sync", headers=admin_headers).json()
    assert run["status"] == "ok"
    assert run["counts"]["updated"] == 1 and run["counts"]["created"] == 0
    assert [s.full_name for s in _students(db_session)] == ["Ana Lopez-Garcia"]


def test_rosters_are_read_page_by_page(client, admin_headers, db_session, sis, monkeypatch):
    monkeypatch.setattr(oneroster_api, "PAGE_SIZE", 2)
    _school(client, admin_headers, "Riverside", "org-a")
    sis.users = [_user(f"s{i}", "Kid", f"Number{i}") for i in range(5)]
    run = client.post("/integrations/sis/sync", headers=admin_headers).json()
    assert run["counts"]["created"] == 5
    offsets = [parse_qs(urlsplit(u).query)["offset"][0] for u, _, _ in sis.calls if "students" in u]
    assert offsets == ["0", "2", "4"]


def test_a_failed_connection_is_recorded_and_admins_are_emailed(
    client,
    admin_headers,
    db_session,
    sis,
    outbox,  # noqa: F811
):
    sis.fail = "The SIS couldn't be reached at https://sis.example.test/oauth/token"
    run = client.post("/integrations/sis/sync", headers=admin_headers).json()
    assert run["status"] == "failed"
    assert "couldn't be reached" in run["error"]
    (message,) = outbox
    assert message["To"] == "admin@example.org"
    assert message["Subject"] == "The SIS roster sync failed"
    assert "secret" not in message.get_content()


def test_needs_attention_emails_counts_but_no_names(client, admin_headers, db_session, sis, outbox):  # noqa: F811
    _school(client, admin_headers, "Riverside", "org-a")
    sis.users = [_user("s3", "Private", "Child", status="tobedeleted")]
    client.post("/integrations/sis/sync", headers=admin_headers)
    (message,) = outbox
    assert message["Subject"] == "The SIS roster sync needs a look"
    assert "1 removal requests" in message.get_content()
    assert "Private" not in message.get_content()


def test_quiet_nights_send_nothing(client, admin_headers, db_session, sis, outbox):  # noqa: F811
    _school(client, admin_headers, "Riverside", "org-a")
    sis.users = [_user("s1", "Ana", "Lopez")]
    client.post("/integrations/sis/sync", headers=admin_headers)
    assert outbox == []


def test_the_nightly_sync_runs_once_after_three(client, admin_headers, db_session, sis):
    _school(client, admin_headers, "Riverside", "org-a")
    sis.users = [_user("s1", "Ana", "Lopez")]
    assert sis_sync.run_if_due(db_session, datetime(2026, 10, 6, 7, 59, tzinfo=UTC)) == 0  # 02:59
    assert sis_sync.run_if_due(db_session, NIGHT) == 1
    assert sis_sync.run_if_due(db_session, NIGHT) == 0  # once a day
    run = db_session.query(SisSyncRun).one()
    assert run.trigger == "scheduled" and run.scheduled_for == date(2026, 10, 6)
    assert run.triggered_by_user_id is None
    assert sis_sync.run_if_due(db_session, datetime(2026, 10, 7, 8, 30, tzinfo=UTC)) == 1


def test_nothing_runs_until_the_connection_is_set_up(client, admin_headers, db_session):
    assert sis_sync.run_if_due(db_session, NIGHT) == 0
    status = client.get("/integrations/sis/sync", headers=admin_headers).json()
    assert status == {"configured": False, "sync_time": "03:00", "runs": []}
    assert client.post("/integrations/sis/sync", headers=admin_headers).status_code == 409


def test_status_lists_runs_newest_first(client, admin_headers, db_session, sis):
    _school(client, admin_headers, "Riverside", "org-a")
    client.post("/integrations/sis/sync", headers=admin_headers)
    client.post("/integrations/sis/sync", headers=admin_headers)
    status = client.get("/integrations/sis/sync", headers=admin_headers).json()
    assert status["configured"] is True
    assert [r["id"] for r in status["runs"]] == sorted(
        (r["id"] for r in status["runs"]), reverse=True
    )


def test_one_sync_at_a_time_and_interrupted_ones_are_closed(client, admin_headers, db_session, sis):
    db_session.add(SisSyncRun(trigger="manual", status="running", started_at=datetime.now(UTC)))
    db_session.commit()
    assert client.post("/integrations/sis/sync", headers=admin_headers).status_code == 409

    stale = db_session.query(SisSyncRun).one()
    stale.started_at = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.commit()
    assert client.post("/integrations/sis/sync", headers=admin_headers).status_code == 200
    db_session.refresh(stale)
    assert stale.status == "failed" and stale.error == "Interrupted before it finished"


def test_only_transportation_admins(client, db_session, sis):
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    headers = auth_headers(login(client, email="disp@example.org"))
    assert client.get("/integrations/sis/sync", headers=headers).status_code == 403
    assert client.post("/integrations/sis/sync", headers=headers).status_code == 403


def test_the_worker_runs_the_sync_job():
    assert ("SIS roster sync", sis_sync.run_if_due) in worker.JOBS


def test_no_personal_details_beyond_name_and_grade_are_kept(client, admin_headers, db_session, sis):
    _school(client, admin_headers, "Riverside", "org-a")
    sis.users = [_user("s1", "Ana", "Lopez")]
    client.post("/integrations/sis/sync", headers=admin_headers)
    student = db_session.query(Student).one()
    assert "kids.example.test" not in str(vars(student))
