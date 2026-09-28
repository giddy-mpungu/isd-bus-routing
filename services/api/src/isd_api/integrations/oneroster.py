"""OneRoster 1.1 CSV adapter for the SIS roster sync (spec section 19,
ADR 0007's "synced read-model" shape).

Pure parsing, deliberately: no database, no framework. It turns a
OneRoster ``users.csv`` into normalized student records plus per-line
problems, so the reconciliation logic (routers/sis_import.py) never sees
vendor column names and a different SIS format could be swapped in behind
the same records. OneRoster is a public standard supported by most SIS
vendors, which is why this is the first adapter rather than any one
vendor's API.

Only what this system needs is read: sourcedId, status, role, givenName,
familyName, orgSourcedIds, and grades (optional; the first grade listed,
normalised to PK/K/1-12, for grade-band walk and ride limits). Nothing
else in the file (email, phone, address-like fields, identifiers) is
retained, in keeping with the README's PII-minimalism rule. Home
addresses are entered in this system and geocoded separately.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from isd_api.eligibility import normalize_grade

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50_000
MAX_NAME_LENGTH = 255
MAX_ID_LENGTH = 64

_REQUIRED_COLUMNS = ("sourcedId", "givenName", "familyName", "orgSourcedIds")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class OneRosterFormatError(ValueError):
    """The upload is not a usable OneRoster users.csv at all (as opposed
    to individual bad rows, which are reported per line)."""


@dataclass(frozen=True)
class RosterStudent:
    line: int
    source_id: str
    full_name: str
    org_ids: tuple[str, ...]
    removal_requested: bool
    # None when the file has no grades column, or the grade isn't one this
    # system uses; the import then leaves the student's grade alone.
    grade: str | None = None


@dataclass(frozen=True)
class RowProblem:
    line: int
    source_id: str | None
    message: str


@dataclass(frozen=True)
class ParsedRoster:
    students: tuple[RosterStudent, ...]
    problems: tuple[RowProblem, ...]
    ignored_non_student_rows: int


def _clean(value: str | None) -> str:
    return _CONTROL_CHARS.sub("", (value or "")).strip()


def parse_students_csv(raw: bytes) -> ParsedRoster:
    if len(raw) > MAX_BYTES:
        raise OneRosterFormatError(f"File is larger than the {MAX_BYTES // (1024 * 1024)} MB limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OneRosterFormatError("File is not valid UTF-8 text") from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    fieldnames = reader.fieldnames or []
    missing = [c for c in _REQUIRED_COLUMNS if c not in fieldnames]
    if missing:
        raise OneRosterFormatError(
            "Not a OneRoster users.csv: missing column(s) " + ", ".join(missing)
        )

    students: list[RosterStudent] = []
    problems: list[RowProblem] = []
    ignored = 0
    seen: dict[str, int] = {}
    try:
        for row_count, row in enumerate(reader, start=1):
            if row_count > MAX_ROWS:
                raise OneRosterFormatError(f"File has more than {MAX_ROWS} rows")
            line = reader.line_num
            # `role` is optional in some exports that contain students only;
            # when present, anything other than a student is not ours to import.
            role = _clean(row.get("role")).lower()
            if role and role != "student":
                ignored += 1
                continue

            source_id = _clean(row.get("sourcedId"))
            if not source_id or len(source_id) > MAX_ID_LENGTH:
                problems.append(RowProblem(line, None, "sourcedId is missing or too long"))
                continue
            if source_id in seen:
                problems.append(
                    RowProblem(
                        line,
                        source_id,
                        f"Duplicate sourcedId (first seen on line {seen[source_id]}); row skipped",
                    )
                )
                continue
            seen[source_id] = line

            given = _clean(row.get("givenName"))
            family = _clean(row.get("familyName"))
            full_name = f"{given} {family}".strip()
            if not full_name:
                problems.append(RowProblem(line, source_id, "Student has no name"))
                continue
            if len(full_name) > MAX_NAME_LENGTH:
                problems.append(RowProblem(line, source_id, "Name is too long"))
                continue

            org_ids = tuple(
                o for o in (_clean(o) for o in (row.get("orgSourcedIds") or "").split(",")) if o
            )
            status = _clean(row.get("status")).lower()
            grades = [g for g in (_clean(g) for g in (row.get("grades") or "").split(",")) if g]
            students.append(
                RosterStudent(
                    line=line,
                    source_id=source_id,
                    full_name=full_name,
                    org_ids=org_ids,
                    removal_requested=status == "tobedeleted",
                    grade=normalize_grade(grades[0]) if grades else None,
                )
            )
    except csv.Error as exc:
        raise OneRosterFormatError(f"Malformed CSV: {exc}") from exc

    return ParsedRoster(
        students=tuple(students), problems=tuple(problems), ignored_non_student_rows=ignored
    )
