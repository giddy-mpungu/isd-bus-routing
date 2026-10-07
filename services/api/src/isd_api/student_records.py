"""A student's transportation records, as one readable file (FERPA's right
to inspect and review, Phase 5).

Decided by the product owner on 2026-10-07: parents download it
themselves from the Family page (students for their own record, and
transportation admins for a request made another way), so the district's
45-day duty is met at once. It holds everything this system keeps about
the child: their details, home address, guardians, ridership changes,
bus-time emails, who at the district viewed the record, and the history
of changes. A plain HTML page: opens in any browser, prints, no scripts.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from isd_api import access_log
from isd_api.i18n import tr
from isd_api.models import (
    AuditLogEntry,
    EtaNotification,
    RecordCorrection,
    RidershipOverride,
    Student,
    StudentAccess,
    StudentHome,
    User,
)
from isd_api.ridership_rules import hhmm, load_rules

LEG = {"am": "Morning", "pm": "Afternoon"}


def _table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f"<p>{escape(empty)}</p>"
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def build(db: Session, student: Student, generated_at: datetime, lang: str = "en") -> str:
    tz = ZoneInfo(load_rules(db).timezone)

    def t(phrase: str, **values: object) -> str:
        return tr(lang, phrase, **values)

    def yes(flag: bool) -> str:
        return t("Yes") if flag else t("No")

    def when(moment: datetime) -> str:
        if moment.tzinfo is None:  # SQLite hands it back without one
            moment = moment.replace(tzinfo=ZoneInfo("UTC"))
        return moment.astimezone(tz).strftime("%Y-%m-%d %H:%M")

    details = [
        [t("Name"), student.full_name],
        [t("School"), student.school.name],
        [t("Grade"), student.grade or t("Not recorded")],
        [t("Bus stop"), student.stop.label if student.stop else t("None assigned")],
        [t("Usually rides"), yes(student.default_ridership.value == "rides")],
        [t("Needs specialized transportation"), yes(student.needs_specialized_transport)],
        [t("Hazardous walking route"), yes(student.hazardous_route)],
        [
            t("Accommodations"),
            ", ".join(sorted(q.description or q.code for q in student.accommodations)) or t("None"),
        ],
        [t("Student ID from the school's records"), student.external_id or t("None")],
    ]
    home = db.get(StudentHome, student.id)
    home_rows = (
        [
            [t("Address"), home.address],
            [t("Matched as"), home.matched_address or t("Placed by hand on a map")],
            [t("Last changed"), when(home.updated_at)],
        ]
        if home
        else []
    )
    guardians = [[g.full_name] for g in sorted(student.guardians, key=lambda g: g.full_name)]
    overrides = [
        [
            o.service_date.isoformat(),
            t(LEG[o.direction.value]),
            t("Riding") if o.is_riding else t("Not riding"),
        ]
        for o in db.query(RidershipOverride)
        .filter(RidershipOverride.student_id == student.id)
        .order_by(RidershipOverride.service_date.desc())
    ]
    emails = [
        [
            n.service_date.isoformat(),
            t(LEG[n.direction.value]),
            hhmm(n.eta_minute),
            when(n.sent_at),
        ]
        for n in db.query(EtaNotification)
        .filter(EtaNotification.student_id == student.id)
        .order_by(EtaNotification.sent_at.desc())
    ]
    views = [
        [
            when(a.first_at),
            u.full_name,
            t(u.role.value.replace("_", " ")),
            t(access_log.WHAT.get(a.what, a.what)),
        ]
        for a, u in db.query(StudentAccess, User)
        .join(User, StudentAccess.user_id == User.id)
        .filter(StudentAccess.student_id == student.id)
        .order_by(StudentAccess.first_at.desc())
    ]
    corrections = [
        [
            when(c.created_at),
            c.what_is_wrong,
            c.should_say,
            t(c.status),
            c.response or "",
        ]
        for c in db.query(RecordCorrection)
        .filter(RecordCorrection.student_id == student.id)
        .order_by(RecordCorrection.created_at.desc())
    ]
    changes = [
        [
            when(e.created_at),
            e.action.replace("_", " "),
            actor.full_name if actor else t("The system"),
        ]
        for e, actor in db.query(AuditLogEntry, User)
        .outerjoin(User, AuditLogEntry.actor_user_id == User.id)
        .filter(AuditLogEntry.entity_type == "student", AuditLogEntry.entity_id == student.id)
        .order_by(AuditLogEntry.created_at.desc())
    ]

    sections = [
        (t("Details"), _table(["", ""], details, "")),
        (t("Home address"), _table(["", ""], home_rows, t("No home address is on file."))),
        (t("Guardians linked to this student"), _table([t("Name")], guardians, t("None."))),
        (
            t("Changes to riding on particular days"),
            _table([t("Date"), t("Trip"), t("Set to")], overrides, t("None.")),
        ),
        (
            t("Bus time emails sent about this student"),
            _table([t("Date"), t("Trip"), t("Time given"), t("Sent")], emails, t("None.")),
        ),
        (
            t("Who at the district viewed this student's information"),
            _table(
                [t("First viewed that day"), t("Who"), t("Role"), t("What")],
                views,
                t("No views recorded."),
            ),
        ),
        (
            t("Correction requests"),
            _table(
                [t("Asked"), t("What was wrong"), t("Should say"), t("Status"), t("Answer")],
                corrections,
                t("None."),
            ),
        ),
        (
            t("Changes to this record"),
            _table([t("When"), t("Change"), t("By")], changes, t("No changes recorded.")),
        ),
    ]
    body = "".join(f"<h2>{escape(title)}</h2>{content}" for title, content in sections)
    title = escape(t("Transportation records: {name}", name=student.full_name))
    intro = escape(
        t(
            "Everything the school bus system holds about this student, as of {when}. If "
            'something here is wrong, use "Something\'s wrong?" on the Family page, or contact '
            "the transportation office.",
            when=when(generated_at),
        )
    )
    return (
        f'<!doctype html>\n<html lang="{escape(lang)}"><head><meta charset="utf-8">\n'
        f"<title>{title}</title>\n<style>{_STYLE}</style></head><body>\n"
        f"<h1>{title}</h1>\n<p>{intro}</p>\n"
        f"{body}\n</body></html>\n"
    )


_STYLE = (
    "body { font-family: system-ui, sans-serif; max-width: 52rem; margin: 2rem auto;"
    " padding: 0 1rem; color: #111; }"
    " table { border-collapse: collapse; width: 100%; margin: 0.5rem 0 1.5rem; }"
    " th, td { border: 1px solid #ccc; padding: 0.35rem 0.5rem; text-align: left;"
    " vertical-align: top; }"
    " th { background: #f3f4f6; }"
)
