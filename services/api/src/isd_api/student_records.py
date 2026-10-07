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
from isd_api.models import (
    AuditLogEntry,
    EtaNotification,
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


def build(db: Session, student: Student, generated_at: datetime) -> str:
    tz = ZoneInfo(load_rules(db).timezone)

    def when(moment: datetime) -> str:
        if moment.tzinfo is None:  # SQLite hands it back without one
            moment = moment.replace(tzinfo=ZoneInfo("UTC"))
        return moment.astimezone(tz).strftime("%Y-%m-%d %H:%M")

    details = [
        ["Name", student.full_name],
        ["School", student.school.name],
        ["Grade", student.grade or "Not recorded"],
        ["Bus stop", student.stop.label if student.stop else "None assigned"],
        [
            "Usually rides",
            "Yes" if student.default_ridership.value == "rides" else "No",
        ],
        [
            "Needs specialized transportation",
            "Yes" if student.needs_specialized_transport else "No",
        ],
        ["Hazardous walking route", "Yes" if student.hazardous_route else "No"],
        [
            "Accommodations",
            ", ".join(sorted(q.description or q.code for q in student.accommodations)) or "None",
        ],
        ["Student ID from the school's records", student.external_id or "None"],
    ]
    home = db.get(StudentHome, student.id)
    home_rows = (
        [
            ["Address", home.address],
            ["Matched as", home.matched_address or "Placed by hand on a map"],
            ["Last changed", when(home.updated_at)],
        ]
        if home
        else []
    )
    guardians = [[g.full_name] for g in sorted(student.guardians, key=lambda g: g.full_name)]
    overrides = [
        [
            o.service_date.isoformat(),
            LEG[o.direction.value],
            "Riding" if o.is_riding else "Not riding",
        ]
        for o in db.query(RidershipOverride)
        .filter(RidershipOverride.student_id == student.id)
        .order_by(RidershipOverride.service_date.desc())
    ]
    emails = [
        [n.service_date.isoformat(), LEG[n.direction.value], hhmm(n.eta_minute), when(n.sent_at)]
        for n in db.query(EtaNotification)
        .filter(EtaNotification.student_id == student.id)
        .order_by(EtaNotification.sent_at.desc())
    ]
    views = [
        [
            when(a.first_at),
            u.full_name,
            u.role.value.replace("_", " "),
            access_log.WHAT.get(a.what, a.what),
        ]
        for a, u in db.query(StudentAccess, User)
        .join(User, StudentAccess.user_id == User.id)
        .filter(StudentAccess.student_id == student.id)
        .order_by(StudentAccess.first_at.desc())
    ]
    changes = [
        [when(e.created_at), e.action.replace("_", " "), actor.full_name if actor else "The system"]
        for e, actor in db.query(AuditLogEntry, User)
        .outerjoin(User, AuditLogEntry.actor_user_id == User.id)
        .filter(AuditLogEntry.entity_type == "student", AuditLogEntry.entity_id == student.id)
        .order_by(AuditLogEntry.created_at.desc())
    ]

    sections = [
        ("Details", _table(["", ""], details, "")),
        ("Home address", _table(["", ""], home_rows, "No home address is on file.")),
        ("Guardians linked to this student", _table(["Name"], guardians, "None.")),
        (
            "Changes to riding on particular days",
            _table(["Date", "Trip", "Set to"], overrides, "None."),
        ),
        (
            "Bus time emails sent about this student",
            _table(["Date", "Trip", "Time given", "Sent"], emails, "None."),
        ),
        (
            "Who at the district viewed this student's information",
            _table(
                ["First viewed that day", "Who", "Role", "What"],
                views,
                "No views recorded.",
            ),
        ),
        (
            "Changes to this record",
            _table(["When", "Change", "By"], changes, "No changes recorded."),
        ),
    ]
    body = "".join(f"<h2>{escape(title)}</h2>{content}" for title, content in sections)
    name = escape(student.full_name)
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
        f"<title>Transportation records: {name}</title>\n<style>{_STYLE}</style></head><body>\n"
        f"<h1>Transportation records: {name}</h1>\n"
        "<p>Everything the school bus system holds about this student, as of "
        f"{escape(when(generated_at))}. If something here is wrong, contact the "
        "transportation office.</p>\n"
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
