"""ORM models.

Column types are chosen to be portable across SQLite (used here, since
this sandboxed environment has no PostgreSQL server to develop/test
against) and PostgreSQL (the intended production database, ADR 0003).
See ADR 0006 for why PostGIS geospatial types are deliberately deferred
rather than used here.

Roles (spec section 17): driver, student, parent, school_admin,
dispatcher, transportation_admin. Student and parent roles are defined
here for RBAC completeness, but the Student/Guardian data model itself
(spec section 3) is NOT part of this phase — see docs/domain-model.md.
Endpoints for those two roles are consequently minimal placeholders
until that data model exists (see routers/).
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from isd_api.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Role(enum.StrEnum):
    DRIVER = "driver"
    STUDENT = "student"
    PARENT = "parent"
    SCHOOL_ADMIN = "school_admin"
    DISPATCHER = "dispatcher"
    TRANSPORTATION_ADMIN = "transportation_admin"


class QualificationKind(enum.StrEnum):
    LICENSE = "license"
    VEHICLE_CAPABILITY = "vehicle_capability"


class AssignmentStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class Qualification(Base):
    """A tag such as CDL_A/CDL_B/NON_CDL_C (driver license quals, spec
    section 1/15) or wheelchair/lift (vehicle capability quals, spec
    section 15). `kind` documents which namespace a code belongs to;
    it is not DB-enforced in this skeleton — application code is
    responsible for only attaching license-kind quals to drivers and
    vehicle_capability-kind quals to vehicles.
    """

    __tablename__ = "qualifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[QualificationKind] = mapped_column(
        SAEnum(QualificationKind, native_enum=False, length=32), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


driver_qualifications = Table(
    "driver_qualifications",
    Base.metadata,
    Column("driver_id", ForeignKey("drivers.id"), primary_key=True),
    Column("qualification_id", ForeignKey("qualifications.id"), primary_key=True),
)

vehicle_qualifications = Table(
    "vehicle_qualifications",
    Base.metadata,
    Column("vehicle_id", ForeignKey("vehicles.id"), primary_key=True),
    Column("qualification_id", ForeignKey("qualifications.id"), primary_key=True),
)

run_required_qualifications = Table(
    "run_required_qualifications",
    Base.metadata,
    Column("run_id", ForeignKey("runs.id"), primary_key=True),
    Column("qualification_id", ForeignKey("qualifications.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(SAEnum(Role, native_enum=False, length=32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Only meaningful when role == DRIVER; links this login to the
    # operational Driver record spec sections 1/13/15 describe.
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("drivers.id"), unique=True, nullable=True
    )
    # Only meaningful when role == SCHOOL_ADMIN; scopes what that user
    # can see to a single school (spec section 17).
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    driver: Mapped[Driver | None] = relationship(back_populates="user")


class School(Base):
    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_lat: Mapped[float] = mapped_column(nullable=False)
    location_lon: Mapped[float] = mapped_column(nullable=False)

    runs: Mapped[list[Run]] = relationship(back_populates="school")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. bus number
    nominal_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    qualifications: Mapped[list[Qualification]] = relationship(secondary=vehicle_qualifications)
    crews: Mapped[list[Crew]] = relationship(back_populates="vehicle")

    def allowable_capacity(self) -> int | None:
        return (
            self.effective_capacity
            if self.effective_capacity is not None
            else self.nominal_capacity
        )


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # District-configured; see isd_solver.domain.Driver docstring — this
    # codebase asserts nothing about what any specific driver-hour law requires.
    max_continuous_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    qualifications: Mapped[list[Qualification]] = relationship(secondary=driver_qualifications)
    crews: Mapped[list[Crew]] = relationship(back_populates="driver")
    user: Mapped[User | None] = relationship(back_populates="driver")


class Crew(Base):
    """A Driver+Vehicle pairing for one service_date (ADR 0001)."""

    __tablename__ = "crews"
    __table_args__ = (
        UniqueConstraint("driver_id", "service_date", name="uq_crew_driver_per_day"),
        UniqueConstraint("vehicle_id", "service_date", name="uq_crew_vehicle_per_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    available_window_earliest: Mapped[int] = mapped_column(Integer, nullable=False)
    available_window_latest: Mapped[int] = mapped_column(Integer, nullable=False)

    driver: Mapped[Driver] = relationship(back_populates="crews")
    vehicle: Mapped[Vehicle] = relationship(back_populates="crews")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="crew")


class Run(Base):
    """One school-bell-window run-instance for one service_date (ADR 0001)."""

    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("id", "service_date", name="uq_run_service_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    window_earliest: Mapped[int] = mapped_column(Integer, nullable=False)
    window_latest: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passenger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    school: Mapped[School] = relationship(back_populates="runs")
    required_qualifications: Mapped[list[Qualification]] = relationship(
        secondary=run_required_qualifications
    )
    assignment: Mapped[Assignment | None] = relationship(back_populates="run", uselist=False)


class Assignment(Base):
    """The persisted output of the solver for one Run (spec sections 11, 21)."""

    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("run_id", name="uq_assignment_one_per_run"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    crew_id: Mapped[int] = mapped_column(ForeignKey("crews.id"), nullable=False)
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured form of the same explanation (ADR 0004) — kept so a
    # UI can render it without re-parsing the text.
    explanation_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # spec section 21: transportation personnel must be able to "lock
    # specific routes or assignments" — a locked assignment survives a
    # re-POST /schedule for its date untouched, and its crew's busy
    # interval for this run is excluded from that re-solve, not the
    # whole crew (see routers/schedule.py; solver-side in
    # isd_solver.Crew.busy_intervals).
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Driver-reported progress (Phase 4) — distinct from `locked`, which
    # is a dispatcher-facing scheduling concept. Set via the driver-only
    # PATCH .../status endpoint, not the dispatcher override endpoint.
    status: Mapped[AssignmentStatus] = mapped_column(
        SAEnum(AssignmentStatus, native_enum=False, length=20),
        default=AssignmentStatus.SCHEDULED,
        nullable=False,
    )
    status_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    run: Mapped[Run] = relationship(back_populates="assignment")
    crew: Mapped[Crew] = relationship(back_populates="assignments")


class AuditLogEntry(Base):
    """Append-only audit trail (spec section 14, ADR 0004).

    Application code must only INSERT here, never UPDATE/DELETE — see
    audit.py. There is deliberately no ORM relationship back from
    other entities to this table, to discourage treating it as
    anything other than an append-only log queried by entity_type/id.
    """

    __tablename__ = "audit_log_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # created/updated/deleted
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
