"""OneRoster users.csv adapter (pure parsing, no database)."""

import pytest

from isd_api.integrations.oneroster import (
    MAX_BYTES,
    OneRosterFormatError,
    parse_students_csv,
)

HEADER = "sourcedId,status,role,givenName,familyName,orgSourcedIds,email\n"


def _csv(*rows: str) -> bytes:
    return (HEADER + "\n".join(rows) + "\n").encode()


def test_parses_students_and_keeps_only_needed_fields():
    parsed = parse_students_csv(
        _csv(
            's1,active,student,Ana,Lopez,"org-a,org-district",ana@example.org',
            "s2,tobedeleted,student,Ben,Ng,org-b,",
        )
    )
    assert [s.source_id for s in parsed.students] == ["s1", "s2"]
    first, second = parsed.students
    assert first.full_name == "Ana Lopez"
    assert first.org_ids == ("org-a", "org-district")
    assert first.removal_requested is False
    assert second.removal_requested is True
    # Email is never carried into the record (PII minimalism).
    assert not hasattr(first, "email")
    assert parsed.problems == ()


def test_non_student_roles_are_ignored_and_counted():
    parsed = parse_students_csv(
        _csv(
            "t1,active,teacher,Tia,Ray,org-a,",
            "g1,active,guardian,Gus,Hall,org-a,",
            "s1,active,student,Ana,Lopez,org-a,",
        )
    )
    assert [s.source_id for s in parsed.students] == ["s1"]
    assert parsed.ignored_non_student_rows == 2


def test_role_column_may_be_absent_and_bom_is_tolerated():
    raw = ("﻿sourcedId,givenName,familyName,orgSourcedIds\ns1,Ana,Lopez,org-a\n").encode()
    parsed = parse_students_csv(raw)
    assert [s.full_name for s in parsed.students] == ["Ana Lopez"]


def test_bad_rows_are_reported_with_line_numbers_not_fatal():
    parsed = parse_students_csv(
        _csv(
            "s1,active,student,Ana,Lopez,org-a,",
            "s1,active,student,Ana,Again,org-a,",  # duplicate id, line 3
            ",active,student,No,Id,org-a,",  # missing id, line 4
            "s3,active,student,,,org-a,",  # nameless, line 5
            "s4,active,student,Cy,Ohm,org-a,",
        )
    )
    assert [s.source_id for s in parsed.students] == ["s1", "s4"]
    by_line = {p.line: p.message for p in parsed.problems}
    assert "Duplicate sourcedId" in by_line[3]
    assert "sourcedId is missing" in by_line[4]
    assert "no name" in by_line[5]


def test_control_characters_are_stripped_from_names_and_ids():
    parsed = parse_students_csv(_csv("s\x001,active,student,A\x07na,Lo\x1fpez,org-a,"))
    (student,) = parsed.students
    assert student.source_id == "s1"
    assert student.full_name == "Ana Lopez"


def test_overlong_name_and_id_are_rejected_per_row():
    parsed = parse_students_csv(
        _csv(
            f"{'x' * 65},active,student,Ana,Lopez,org-a,",
            f"s2,active,student,{'n' * 200},{'m' * 200},org-a,",
        )
    )
    assert parsed.students == ()
    assert len(parsed.problems) == 2


@pytest.mark.parametrize(
    "raw",
    [
        b"name,grade\nAna,3\n",  # not a OneRoster file
        b"\xff\xfe\x00bad",  # not UTF-8
        b"",  # empty
    ],
)
def test_unusable_files_raise(raw):
    with pytest.raises(OneRosterFormatError):
        parse_students_csv(raw)


def test_oversized_file_is_rejected():
    with pytest.raises(OneRosterFormatError, match="larger than"):
        parse_students_csv(b"x" * (MAX_BYTES + 1))


def test_formula_like_names_are_kept_verbatim_not_evaluated():
    """Stored as plain text; nothing here evaluates or exports it."""
    parsed = parse_students_csv(_csv("s1,active,student,=SUM(A1),Lopez,org-a,"))
    assert parsed.students[0].full_name == "=SUM(A1) Lopez"
