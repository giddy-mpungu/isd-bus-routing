"""Reconciling a roster against the students table (spec section 19;
ADR 0007: the SIS is authoritative for student identity, name, school and
grade; this system stays authoritative for stop assignment and ridership,
which are never touched).

Shared by the manual CSV upload (routers/sis_import.py) and the scheduled
OneRoster API sync (isd_api/sis_sync.py), so both follow exactly the same
rules. Anything that would need a guess is reported for a person instead
of applied (spec section 21): an unmapped or ambiguous school, a possible
duplicate of a hand-entered student, a removal request.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.integrations.oneroster import ParsedRoster, RosterStudent
from isd_api.models import School, Student, User
from isd_api.schemas import SisImportResult, SisImportRow

MAX_RETURNED_ROWS = 1000


def _school_for(
    student: RosterStudent, schools_by_external_id: dict[str, School]
) -> tuple[School | None, str | None]:
    mapped = [schools_by_external_id[o] for o in student.org_ids if o in schools_by_external_id]
    unique = {s.id: s for s in mapped}
    if len(unique) == 1:
        return next(iter(unique.values())), None
    if not unique:
        return None, (
            "None of this student's organizations is mapped to a school here; "
            "set the school's SIS ID first"
        )
    return None, "Student belongs to more than one mapped school; not guessing which applies"


def reconcile(
    db: Session,
    parsed: ParsedRoster,
    *,
    dry_run: bool,
    link_by_name: bool,
    actor: User | None,
    audit_prefix: str = "sis_import",
) -> SisImportResult:
    """Applies (unless dry_run) what the roster changes, and reports every
    row's outcome. link_by_name: see routers/sis_import.py. Commits when
    not a dry run."""
    schools_by_external_id = {
        s.external_id: s for s in db.query(School).all() if s.external_id is not None
    }
    existing_by_external_id = {
        s.external_id: s for s in db.query(Student).all() if s.external_id is not None
    }
    unlinked = db.query(Student).filter(Student.external_id.is_(None)).all()

    counts = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "linked": 0,
        "needs_review": 0,
        "removal_requested": 0,
        "error": 0,
    }
    rows: list[SisImportRow] = []

    def add(
        line: int,
        source_id: str | None,
        name: str | None,
        action: str,
        detail: str | None = None,
        student_id: int | None = None,
    ) -> None:
        counts[action] += 1
        if action != "unchanged":
            rows.append(
                SisImportRow(
                    line=line,
                    source_id=source_id,
                    full_name=name,
                    action=action,
                    detail=detail,
                    student_id=student_id,
                )
            )

    for problem in parsed.problems:
        add(problem.line, problem.source_id, None, "error", problem.message)

    for rs in parsed.students:
        existing = existing_by_external_id.get(rs.source_id)

        if rs.removal_requested:
            # Never applied: a student can have overrides and history, and a
            # roster flag is not a reason to erase them without a human.
            add(
                rs.line,
                rs.source_id,
                rs.full_name,
                "removal_requested",
                "SIS marked this student for deletion; not applied, remove manually if intended",
                existing.id if existing else None,
            )
            continue

        school, school_problem = _school_for(rs, schools_by_external_id)
        if school is None:
            add(rs.line, rs.source_id, rs.full_name, "error", school_problem)
            continue

        if existing is not None:
            new_grade = rs.grade if rs.grade is not None else existing.grade
            changed = (
                existing.full_name != rs.full_name
                or existing.school_id != school.id
                or existing.grade != new_grade
            )
            if not changed:
                add(rs.line, rs.source_id, rs.full_name, "unchanged", None, existing.id)
                continue
            details = []
            if existing.full_name != rs.full_name:
                details.append(f"name '{existing.full_name}' -> '{rs.full_name}'")
            if existing.school_id != school.id:
                details.append(f"school {existing.school_id} -> {school.id}")
            if existing.grade != new_grade:
                details.append(f"grade {existing.grade or 'none'} -> {new_grade}")
            add(rs.line, rs.source_id, rs.full_name, "updated", "; ".join(details), existing.id)
            if not dry_run:
                before = {
                    "full_name": existing.full_name,
                    "school_id": existing.school_id,
                    "grade": existing.grade,
                }
                existing.full_name = rs.full_name
                existing.school_id = school.id
                existing.grade = new_grade
                db.flush()
                record_audit(
                    db,
                    entity_type="student",
                    entity_id=existing.id,
                    action=f"{audit_prefix}_updated",
                    actor=actor,
                    before_state=before,
                    after_state={
                        "full_name": existing.full_name,
                        "school_id": existing.school_id,
                        "grade": existing.grade,
                    },
                )
            continue

        candidates = [
            s for s in unlinked if s.full_name == rs.full_name and s.school_id == school.id
        ]
        if len(candidates) > 1:
            add(
                rs.line,
                rs.source_id,
                rs.full_name,
                "needs_review",
                f"{len(candidates)} hand-entered students share this name at this school; "
                "not guessing which one",
            )
            continue
        if len(candidates) == 1:
            match = candidates[0]
            if not link_by_name:
                add(
                    rs.line,
                    rs.source_id,
                    rs.full_name,
                    "needs_review",
                    f"Same name and school as hand-entered student {match.id}; re-run with "
                    "'link by name' to attach the SIS ID to it instead of creating a duplicate",
                    match.id,
                )
                continue
            add(rs.line, rs.source_id, rs.full_name, "linked", "Attached SIS ID by name", match.id)
            # Claimed in memory even on a dry run, so two roster rows can't
            # both report linking to the same hand-entered student.
            unlinked.remove(match)
            if not dry_run:
                match.external_id = rs.source_id
                if rs.grade is not None:
                    match.grade = rs.grade
                existing_by_external_id[rs.source_id] = match
                db.flush()
                record_audit(
                    db,
                    entity_type="student",
                    entity_id=match.id,
                    action=f"{audit_prefix}_linked",
                    actor=actor,
                    before_state={"external_id": None},
                    after_state={"external_id": rs.source_id},
                )
            continue

        add(rs.line, rs.source_id, rs.full_name, "created")
        if not dry_run:
            created = Student(
                full_name=rs.full_name,
                school_id=school.id,
                external_id=rs.source_id,
                grade=rs.grade,
            )
            db.add(created)
            db.flush()
            existing_by_external_id[rs.source_id] = created
            record_audit(
                db,
                entity_type="student",
                entity_id=created.id,
                action=f"{audit_prefix}_created",
                actor=actor,
                after_state={
                    "full_name": created.full_name,
                    "school_id": created.school_id,
                    "grade": created.grade,
                    "external_id": rs.source_id,
                },
            )

    if not dry_run:
        db.commit()

    rows.sort(key=lambda r: r.line)
    return SisImportResult(
        dry_run=dry_run,
        counts=counts,
        rows=rows[:MAX_RETURNED_ROWS],
        rows_truncated=len(rows) > MAX_RETURNED_ROWS,
        ignored_non_student_rows=parsed.ignored_non_student_rows,
    )
