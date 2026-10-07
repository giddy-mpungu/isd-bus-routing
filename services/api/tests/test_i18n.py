"""Translations (isd_api/i18n): Spanish for what families and drivers read.

The catalog checks keep a language complete as the code changes: every
phrase the code translates must be in every catalog, with the same
placeholders, and a catalog keeps no phrase the code no longer uses."""

import ast
import re
from pathlib import Path
from types import SimpleNamespace

from isd_api import account_emails, eta_notifications, i18n
from isd_api.assignment_states import LABELS, driver_transition_problem
from isd_api.daily_trip import TripStop
from isd_api.i18n import tr, translate_message
from isd_api.models import AssignmentStatus, RideDirection, Role, User
from tests.conftest import auth_headers, login, make_user
from tests.test_email import outbox  # noqa: F401  (fixture)
from tests.test_ridership_rules import (
    DAY,
    _declare,
    _parent_of,
    _rules,
    _school,
    _student,
    at_noon_utc,  # noqa: F401  (fixture)
)

SRC = Path(__file__).resolve().parents[1] / "src" / "isd_api"
ES = {"Accept-Language": "es-US,es;q=0.9,en;q=0.8"}
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _source_strings() -> set[str]:
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        if path.parent.name == "i18n":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
    return found


def _translated_literals() -> set[str]:
    """Every phrase passed to tr() as a literal (or a literal if/else)."""
    phrases: set[str] = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == "tr" and len(node.args) >= 2:
                arg = node.args[1]
            elif name == "t" and node.args:
                arg = node.args[0]
            else:
                continue
            options = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
            phrases |= {o.value for o in options if isinstance(o, ast.Constant)}
    return phrases


# Looked up by value at run time rather than written as a tr() literal.
DYNAMIC = {
    *(label.lower() for label in LABELS.values()),
    *(role.value.replace("_", " ") for role in Role),
    "open",
    "accepted",
    "declined",
    "morning pickup",
    "afternoon drop-off",
    "Morning",
    "Afternoon",
}


def test_every_catalog_has_every_translated_phrase():
    needed = _translated_literals() | DYNAMIC
    for lang, catalog in i18n.CATALOGS.items():
        missing = sorted(needed - catalog.keys())
        assert missing == [], f"{lang} is missing {missing}"


def test_translations_keep_their_placeholders():
    for lang, catalog in i18n.CATALOGS.items():
        for phrase, translated in catalog.items():
            assert set(PLACEHOLDER.findall(phrase)) == set(PLACEHOLDER.findall(translated)), (
                lang,
                phrase,
            )


def test_catalogs_hold_no_phrase_the_code_no_longer_uses():
    used = _source_strings() | DYNAMIC
    for lang, catalog in i18n.CATALOGS.items():
        stale = sorted(p for p in catalog if p not in used)
        assert stale == [], f"{lang} has unused phrases {stale}"


def test_accept_language_picks_the_best_supported_language():
    assert i18n.from_accept_language("es-MX,es;q=0.9,en;q=0.8") == "es"
    assert i18n.from_accept_language("fr-FR,fr;q=0.9,es;q=0.5") == "es"
    assert i18n.from_accept_language("en;q=0.4,es;q=0.6") == "es"
    assert i18n.from_accept_language("es;q=0,en") == "en"
    assert i18n.from_accept_language("de") == "en"
    assert i18n.from_accept_language(None) == "en"
    assert i18n.normalize("es_US") == "es"
    assert i18n.normalize("xx") == "en"


def test_finished_messages_are_recognised_with_their_values():
    assert translate_message("es", "Use at least 8 characters") == "Use al menos 8 caracteres"
    problem = driver_transition_problem(AssignmentStatus.COMPLETED, AssignmentStatus.EN_ROUTE)
    assert problem is not None
    assert translate_message("es", problem) == "Esta asignación ya está marcada como completada."
    assert translate_message("es", "Something nobody translated") == "Something nobody translated"
    assert translate_message("en", "Use at least 8 characters") == "Use at least 8 characters"
    # Short templates are never used to recognise a message.
    assert translate_message("es", "3 days") == "3 days"
    assert tr("es", "{count} days", count=3) == "3 días"


def test_errors_come_back_in_the_language_asked_for(client, db_session):
    make_user(db_session, email="pat@example.org", role=Role.PARENT)
    wrong = {"username": "pat@example.org", "password": "not-it"}
    spanish = client.post("/auth/login", data=wrong, headers=ES)
    assert spanish.status_code == 401
    assert spanish.json()["detail"] == "Correo electrónico o contraseña incorrectos"
    assert spanish.headers["www-authenticate"] == "Bearer"
    english = client.post("/auth/login", data=wrong)
    assert english.json()["detail"] == "Incorrect email or password"


def test_families_read_closed_legs_in_spanish(client, admin_headers, db_session, at_noon_utc):  # noqa: F811
    _rules(client, admin_headers, am=360)
    student = _student(client, admin_headers, _school(client, admin_headers), "Jamie")
    parent = _parent_of(client, admin_headers, db_session, student)

    [today] = client.get(
        "/students/my-family", headers={**parent, **ES}, params={"service_date": DAY}
    ).json()
    assert today["am_changes_closed"] == (
        "Los cambios al viaje AM de hoy se cerraron a las 06:00. Comuníquese con la oficina "
        "de transporte."
    )
    refused = _declare(client, {**parent, **ES}, student, riding=False)
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("Los cambios al viaje AM")


def test_people_choose_their_language(client, db_session):
    make_user(db_session, email="pat@example.org", role=Role.PARENT)
    headers = auth_headers(login(client, email="pat@example.org"))
    assert client.get("/users/me", headers=headers).json()["preferred_language"] is None

    chosen = client.put("/users/me/language", headers=headers, json={"language": "es"})
    assert chosen.status_code == 200
    assert chosen.json()["preferred_language"] == "es"
    assert client.get("/users/me", headers=headers).json()["preferred_language"] == "es"
    bad = client.put("/users/me/language", headers=headers, json={"language": "xx"})
    assert bad.status_code == 400


def test_admins_can_set_a_new_familys_email_language(client, admin_headers):
    created = client.post(
        "/users",
        headers=admin_headers,
        json={
            "email": "rosa@example.org",
            "password": "yellow-bus-route-7",
            "full_name": "Rosa Diaz",
            "role": "parent",
            "preferred_language": "es",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["preferred_language"] == "es"
    unknown = client.post(
        "/users",
        headers=admin_headers,
        json={
            "email": "lee@example.org",
            "password": "yellow-bus-route-7",
            "full_name": "Lee",
            "role": "parent",
            "preferred_language": "klingon",
        },
    )
    assert unknown.status_code == 400


def test_account_emails_follow_the_persons_language(client, db_session, outbox):  # noqa: F811
    make_user(
        db_session,
        email="rosa@example.org",
        role=Role.PARENT,
        full_name="Rosa Diaz",
        preferred_language="es",
    )
    assert client.post("/auth/forgot-password", json={"email": "rosa@example.org"}).status_code
    [message] = outbox
    body = message.get_content()
    assert message["Subject"] == "Restablezca la contraseña de la aplicación del autobús"
    assert body.startswith("Hola, Rosa Diaz:")
    assert "en un plazo de 1 hora" in body
    assert "pendiente de revisión" in body
    assert "https://bus.example.test/reset-password#token=" in body


def test_english_emails_are_unchanged():
    user = User(email="pat@example.org", full_name="Pat", role=Role.PARENT)
    body = account_emails.password_changed_email(user).body
    assert body == (
        "Hello Pat,\n\nThe password for your account was just changed, and you were signed out "
        "on your other devices.\n\nIf this wasn't you, contact your transportation office "
        "straight away.\n\nisd-bus-routing, your district's school transportation system\n"
    )


def test_bus_time_emails_in_spanish():
    parent = User(
        id=7, email="rosa@example.org", full_name="Rosa", role=Role.PARENT, preferred_language="es"
    )
    student = SimpleNamespace(full_name="Ana Diaz")
    stop = TripStop(
        position=1,
        stop_id=1,
        label="Elm St",
        riders=[],
        skipped=False,
        planned_minute=7 * 60 + 30,
        eta_minute=7 * 60 + 45,
    )
    email = eta_notifications.change_email(parent, student, RideDirection.AM, stop)  # type: ignore[arg-type]
    assert email.subject == "Cambio de horario del autobús de Ana Diaz: 07:45"
    assert (
        "La recogida de la mañana de hoy de Ana Diaz en Elm St ahora se espera alrededor de "
        "las 07:45 (prevista a las 07:30)." in email.body
    )


def test_the_records_download_is_in_the_familys_language(client, admin_headers, db_session):
    student = _student(client, admin_headers, _school(client, admin_headers), "Jamie Diaz")
    parent = _parent_of(client, admin_headers, db_session, student)
    page = client.get(f"/students/{student['id']}/records", headers={**parent, **ES}).text
    assert '<html lang="es">' in page
    assert "Expediente de transporte: Jamie Diaz" in page
    assert "Viaja normalmente" in page

    user = db_session.query(User).filter(User.email == "parent@example.org").one()
    user.preferred_language = "en"
    db_session.commit()
    page = client.get(f"/students/{student['id']}/records", headers={**parent, **ES}).text
    assert "Transportation records: Jamie Diaz" in page
