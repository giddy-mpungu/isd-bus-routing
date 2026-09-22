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


class RidershipDefault(enum.StrEnum):
    """spec section 4.1: a student's configured default ridership state,
    overridden per-day by RidershipOverride."""

    RIDES = "rides"
    DOES_NOT_RIDE = "does_not_ride"


class RideDirection(enum.StrEnum):
    """spec section 4.2: AM/PM are independent legs — a student may ride
    to school but not home, or vice versa."""

    AM = "am"
    PM = "pm"


class AnnouncementAudience(enum.StrEnum):
    """Who a dispatcher-authored Announcement is for -- matches spec
    section 9's "Messages from dispatch" (driver) and section 18's
    "Transportation announcements"/"Delay notifications"/"Bus
    substitution notices"/"Route-change notices" (family)."""

    ALL = "all"
    FAMILY = "family"
    DRIVER = "driver"


class AnnouncementCategory(enum.StrEnum):
    """Informational only -- doesn't change delivery, just lets the UI
    label a notice the way spec sections 9/18 name their categories.
    See Announcement's own docstring for why these are always
    dispatcher-authored, never auto-detected."""

    GENERAL = "general"
    DELAY = "delay"
    SUBSTITUTION = "substitution"
    ROUTE_CHANGE = "route_change"


class TripStatus(enum.StrEnum):
    """spec section 12's enumerated field-trip lifecycle, in order."""

    REQUESTED = "requested"
    APPROVED = "approved"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    RETURNING = "returning"
    COMPLETED = "completed"


class AbsenceReason(enum.StrEnum):
    """spec section 13's enumerated reasons. "Partial-day absence" is
    deliberately not a value here — it's already representable via
    DriverAbsence.start_minute/end_minute not spanning the full day, a
    separate enum value would be redundant with that."""

    SICK_LEAVE = "sick_leave"
    PERSONAL_DAY = "personal_day"
    VACATION = "vacation"
    EMERGENCY_LEAVE = "emergency_leave"
    TRAINING = "training"
    APPROVED_LEAVE = "approved_leave"
    ADMINISTRATIVE_DIRECTION = "administrative_direction"
    INJURY = "injury"
    NO_CALL_NO_SHOW = "no_call_no_show"
    OTHER = "other"


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
    # A retired qualification code: hidden from future assignment (driver/
    # vehicle/run/template qualification pickers), never hard-deleted --
    # existing many-to-many rows referencing it by id stay meaningful.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


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

route_template_required_qualifications = Table(
    "route_template_required_qualifications",
    Base.metadata,
    Column("route_template_id", ForeignKey("route_templates.id"), primary_key=True),
    Column("qualification_id", ForeignKey("qualifications.id"), primary_key=True),
)

field_trip_required_qualifications = Table(
    "field_trip_required_qualifications",
    Base.metadata,
    Column("field_trip_id", ForeignKey("field_trips.id"), primary_key=True),
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
    # Only meaningful when role == STUDENT; a student's own login,
    # spec section 17's separate "Student" role (distinct from a
    # parent/guardian's access via the student_guardians table below —
    # a parent isn't "a" student).
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    driver: Mapped[Driver | None] = relationship(back_populates="user")
    guardian_of: Mapped[list[Student]] = relationship(
        secondary="student_guardians", back_populates="guardians"
    )


class School(Base):
    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_lat: Mapped[float] = mapped_column(nullable=False)
    location_lon: Mapped[float] = mapped_column(nullable=False)
    # The SIS's identifier for this school (OneRoster org sourcedId). Set
    # by an administrator, never inferred: a roster row can only be
    # placed at a school someone has explicitly mapped (ADR 0007).
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    runs: Mapped[list[Run]] = relationship(back_populates="school")


class Stop(Base):
    """A physical boarding/alighting location (spec section 3). Phase 5
    MVP only: manually created by transportation personnel — spec
    section 3's automated stop-generation algorithm (walking distance,
    road safety constraints) needs GIS/road-network data this project
    doesn't have yet (PostGIS is deferred, ADR 0006) and is out of
    scope until that exists."""

    __tablename__ = "stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    location_lat: Mapped[float] = mapped_column(nullable=False)
    location_lon: Mapped[float] = mapped_column(nullable=False)


class Student(Base):
    """spec section 3. Deliberately minimal fields — no home address is
    collected here, even though spec section 3 mentions it, because
    nothing in this phase consumes it (automated stop generation is
    deferred); same PII-minimalism precedent as Driver above."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    # SIS identifier (OneRoster user sourcedId); NULL for students entered
    # by hand. The SIS owns name and school assignment for rows that have
    # one; stop_id and default_ridership stay owned by this system.
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    stop_id: Mapped[int | None] = mapped_column(ForeignKey("stops.id"), nullable=True)
    default_ridership: Mapped[RidershipDefault] = mapped_column(
        SAEnum(RidershipDefault, native_enum=False, length=20),
        default=RidershipDefault.RIDES,
        nullable=False,
    )

    school: Mapped[School] = relationship()
    stop: Mapped[Stop | None] = relationship()
    guardians: Mapped[list[User]] = relationship(
        secondary="student_guardians", back_populates="guardian_of"
    )


# A parent/guardian's access to a student's data (spec section 17) —
# many-to-many since a parent may have multiple children and, less
# commonly but really, a student may have more than one guardian with
# app access. Distinct from User.student_id above, which is a
# student's own login, not a guardian's.
student_guardians = Table(
    "student_guardians",
    Base.metadata,
    Column("student_id", ForeignKey("students.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)


class RidershipOverride(Base):
    """spec section 4.2: a per-day, per-leg (AM/PM) override of a
    student's default ridership state — e.g. "not riding AM" for one
    date. Absence of a row for a (student, date, direction) means "use
    Student.default_ridership." Also spec section 4.5's "late request
    to ride": flipping a Does-Not-Ride default's override to
    is_riding=True for one day uses this exact same mechanism, no
    separate code path needed."""

    __tablename__ = "ridership_overrides"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "service_date", "direction", name="uq_ridership_override_leg"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[RideDirection] = mapped_column(
        SAEnum(RideDirection, native_enum=False, length=8), nullable=False
    )
    is_riding: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. bus number
    nominal_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # spec section 6 vehicle profile. Persisted only — not yet consumed by
    # routing (isd_solver.domain.Vehicle's own docstring names the follow-up).
    length_m: Mapped[float | None] = mapped_column(nullable=True)
    width_m: Mapped[float | None] = mapped_column(nullable=True)
    height_m: Mapped[float | None] = mapped_column(nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(nullable=True)
    # A retired/out-of-service vehicle: hidden from future crew-creation
    # dropdowns, but never hard-deleted -- existing Crew/Assignment/
    # FieldTrip/CrewTemplate rows referencing it, and everything derived
    # from them (audit log, observed-duration learning), stay intact.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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
    # A departed/inactive driver: hidden from future crew-creation
    # dropdowns, never hard-deleted -- same reasoning as Vehicle.is_active.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    qualifications: Mapped[list[Qualification]] = relationship(secondary=driver_qualifications)
    crews: Mapped[list[Crew]] = relationship(back_populates="driver")
    user: Mapped[User | None] = relationship(back_populates="driver")


class DriverAbsence(Base):
    """spec section 13. Deliberately minimal — no free-text detail
    field ("should not require unnecessary medical details"); who
    reported it is captured by the existing audit-log mechanism
    (actor on the create call), not a column here."""

    __tablename__ = "driver_absences"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[AbsenceReason] = mapped_column(
        SAEnum(AbsenceReason, native_enum=False, length=32), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    driver: Mapped[Driver] = relationship()


class DriverReportType(enum.StrEnum):
    """spec section 9's driver-app "Incident reporting" and "Vehicle
    defect reporting" -- one type discriminator rather than two nearly
    identical entities, same shape as GeographicKnowledgeCategory."""

    INCIDENT = "incident"
    VEHICLE_DEFECT = "vehicle_defect"


class DriverReport(Base):
    """spec section 9. `vehicle_id` is deliberately not driver-supplied
    -- the router resolves it from the driver's own Crew for
    `service_date` (the vehicle they were actually driving), so the
    driver-app form only ever needs a type and a description (spec
    section 9: "minimal typing"). Nullable because a driver may have no
    crew that date, or an incident may not involve a specific vehicle."""

    __tablename__ = "driver_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), nullable=False)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_type: Mapped[DriverReportType] = mapped_column(
        SAEnum(DriverReportType, native_enum=False, length=20), nullable=False
    )
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    driver: Mapped[Driver] = relationship()
    vehicle: Mapped[Vehicle | None] = relationship()


class GeographicKnowledgeCategory(enum.StrEnum):
    """spec section 8's example list of local roadway knowledge."""

    FREQUENT_FLOODING = "frequent_flooding"
    DIFFICULT_INTERSECTION = "difficult_intersection"
    UNSAFE_TURN = "unsafe_turn"
    INVALID_TURNAROUND = "invalid_turnaround"
    CONGESTION_WINDOW = "congestion_window"
    VEHICLE_SIZE_RESTRICTED = "vehicle_size_restricted"
    PREFERRED_ENTRANCE = "preferred_entrance"
    OTHER = "other"


class RestrictedVehicleDimension(enum.StrEnum):
    """Which of Vehicle's own size fields a VEHICLE_SIZE_RESTRICTED
    override's max_allowed_value is measured against -- the string
    values are deliberately identical to Vehicle's own column names
    (isd_solver.domain.SizeRestriction.dimension does a plain
    getattr(vehicle, dimension) against them)."""

    LENGTH_M = "length_m"
    WIDTH_M = "width_m"
    HEIGHT_M = "height_m"
    WEIGHT_KG = "weight_kg"


class GeographicKnowledgeOverride(Base):
    """spec section 8: local roadway information transportation personnel
    know that commercial mapping data doesn't ("this intersection is
    difficult for full-size buses," "this lot isn't a valid turnaround").
    Per ADR 0007, this is the one piece of routing-relevant data this
    system owns itself, layered on top of an external routing provider's
    output rather than merged into it. `note` is required free text:
    unlike DriverAbsence (which deliberately avoids free text for PII
    reasons), the entire value of this entity is staff-authored
    institutional knowledge, which a category alone can't carry. Who
    added it is the audit log, not a column here, same precedent as
    DriverAbsence.

    `window_start_minute`/`window_end_minute` (required together, and
    only meaningful, for CONGESTION_WINDOW), `restricted_dimension`/
    `max_allowed_value` (required together, and only meaningful, for
    VEHICLE_SIZE_RESTRICTED), and `school_id` (required, and only
    meaningful, for PREFERRED_ENTRANCE) are the routing-wiring fields
    for those three categories -- see routers/schedule.py for how
    they're actually applied to a solve. Every other category leaves
    all five null; schemas.GeographicKnowledgeOverrideCreate enforces
    this pairing.

    PREFERRED_ENTRANCE's own `location_lat`/`location_lon` ARE the
    entrance's coordinates -- linking it to a `school_id` says which
    school's regular runs should route to that point instead of the
    school's own centroid (spec section 8's own example, "use the
    north gate for field trips," reinterpreted for the runs this
    system's solver actually schedules; field trips use
    `DestinationProfile.approved_entrance` instead, a separate
    free-text field, since field trips are never solved by CP-SAT)."""

    __tablename__ = "geographic_knowledge_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_lat: Mapped[float] = mapped_column(nullable=False)
    location_lon: Mapped[float] = mapped_column(nullable=False)
    category: Mapped[GeographicKnowledgeCategory] = mapped_column(
        SAEnum(GeographicKnowledgeCategory, native_enum=False, length=32), nullable=False
    )
    note: Mapped[str] = mapped_column(String(1000), nullable=False)
    window_start_minute: Mapped[int | None] = mapped_column(nullable=True)
    window_end_minute: Mapped[int | None] = mapped_column(nullable=True)
    restricted_dimension: Mapped[RestrictedVehicleDimension | None] = mapped_column(
        SAEnum(RestrictedVehicleDimension, native_enum=False, length=16), nullable=True
    )
    max_allowed_value: Mapped[float | None] = mapped_column(nullable=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    school: Mapped[School | None] = relationship()


class RouteTemplate(Base):
    """ADR 0001's "Route": the permanent template a Run is generated from
    (spec section 11 "Permanent Assignment"). Deliberately owns no
    driver/vehicle -- who serves it on a given day is still decided by
    the solver, so multi-school consolidation keeps working. Recurrence
    is a plain weekday list plus an optional active date range, not a
    full RFC 5545 rule."""

    __tablename__ = "route_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    direction: Mapped[RideDirection] = mapped_column(
        SAEnum(RideDirection, native_enum=False, length=8), nullable=False
    )
    window_earliest: Mapped[int] = mapped_column(Integer, nullable=False)
    window_latest: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Python weekday numbers: Monday=0 .. Sunday=6.
    days_of_week: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    school: Mapped[School] = relationship()
    required_qualifications: Mapped[list[Qualification]] = relationship(
        secondary=route_template_required_qualifications
    )


class CrewTemplate(Base):
    """The recurring counterpart of Crew: a driver+vehicle pairing that
    is normally available on certain weekdays. Independent of
    RouteTemplate on purpose (ADR 0001: drivers and vehicles stay
    independently modeled resources)."""

    __tablename__ = "crew_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    available_window_earliest: Mapped[int] = mapped_column(Integer, nullable=False)
    available_window_latest: Mapped[int] = mapped_column(Integer, nullable=False)
    days_of_week: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    driver: Mapped[Driver] = relationship()
    vehicle: Mapped[Vehicle] = relationship()


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
    # Set only when generated from a CrewTemplate; hand-made crews leave
    # it NULL. Provenance, not ownership -- editing a generated crew
    # never touches its template.
    crew_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_templates.id"), nullable=True
    )

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
    # spec section 4.2: which leg this run serves — needed to join
    # against RidershipOverride (keyed by student/date/direction) for
    # the expected-riders decision support (routers/runs.py). Does not
    # affect solver scheduling at all; SolverJob has no direction.
    direction: Mapped[RideDirection] = mapped_column(
        SAEnum(RideDirection, native_enum=False, length=8), nullable=False
    )
    window_earliest: Mapped[int] = mapped_column(Integer, nullable=False)
    window_latest: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passenger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Set only when generated from a RouteTemplate (ADR 0001's Route);
    # NULL for hand-made runs. Also what makes generation idempotent.
    route_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("route_templates.id"), nullable=True
    )

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


class VehiclePosition(Base):
    """spec section 9/18 (ADR 0009): the latest known GPS position for a
    crew's vehicle. One row per crew, overwritten in place -- MVP scope
    is "where is the bus right now," not a breadcrumb trail (ADR 0009
    names that as a deliberate, unbuilt follow-up for spec section 20).
    Reported by the driver's own tablet (browser Geolocation API, ADR
    0009) via PUT /drivers/{id}/position, keyed to a crew rather than a
    specific assignment since a crew's position is meaningful for the
    whole day, not just its current run."""

    __tablename__ = "vehicle_positions"
    __table_args__ = (UniqueConstraint("crew_id", name="uq_vehicle_position_one_per_crew"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_id: Mapped[int] = mapped_column(ForeignKey("crews.id"), nullable=False)
    location_lat: Mapped[float] = mapped_column(nullable=False)
    location_lon: Mapped[float] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    crew: Mapped[Crew] = relationship()


class DestinationProfile(Base):
    """spec section 12.3: reusable transportation-specific information
    for a frequently used field-trip destination -- approved entrance,
    parking, turn restrictions, driver notes. Deliberately its own
    entity a `FieldTrip` optionally links to (`destination_profile_id`)
    rather than fields bolted onto `FieldTrip` itself: the whole point
    is reuse across many trips to the same place, and `FieldTrip.destination`
    stays free text so a one-off destination never requires creating a
    profile first."""

    __tablename__ = "destination_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_lat: Mapped[float | None] = mapped_column(nullable=True)
    location_lon: Mapped[float | None] = mapped_column(nullable=True)
    approved_entrance: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parking_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    turn_restrictions: Mapped[str | None] = mapped_column(String(500), nullable=True)
    driver_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class FieldTrip(Base):
    """spec section 12: a field trip / special assignment, scheduled
    through the same engine as regular routes but NOT run through the
    CP-SAT solver -- driver/vehicle assignment here is a manual
    dispatcher decision (spec section 21: decision support), matching
    how Phase 6's substitute-coverage ranking works, not an
    auto-optimized job. `assigned_driver_id`/`assigned_vehicle_id` are
    direct FKs rather than a `Crew` pairing, since spec section 11's
    "Daily Operational Assignment" (a driver's day as a dynamic
    sequence of jobs, of which a field trip is one kind) isn't built as
    its own abstraction -- a field trip doesn't need a day-long
    Crew row, just a driver+vehicle for this one trip.

    Deliberately minimal versus the full spec section 12 field list:
    "Vehicle requirements" and "Accessibility requirements" share one
    `required_qualifications` (this system already models both through
    `Qualification`, e.g. a wheelchair-lift tag covers both without
    inventing a second namespace); `bus_assistant_name` is free text,
    not a second staff entity (no other staff type exists in this
    schema to justify one)."""

    __tablename__ = "field_trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    requesting_party: Mapped[str] = mapped_column(String(255), nullable=False)
    origin: Mapped[str] = mapped_column(String(255), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("destination_profiles.id"), nullable=True
    )
    departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_return_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_return_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    passenger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assigned_driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), nullable=True)
    assigned_vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id"), nullable=True
    )
    bus_assistant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trip_contact: Mapped[str] = mapped_column(String(255), nullable=False)
    special_instructions: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[TripStatus] = mapped_column(
        SAEnum(TripStatus, native_enum=False, length=20),
        default=TripStatus.REQUESTED,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    destination_profile: Mapped[DestinationProfile | None] = relationship()

    required_qualifications: Mapped[list[Qualification]] = relationship(
        secondary=field_trip_required_qualifications
    )
    assigned_driver: Mapped[Driver | None] = relationship(foreign_keys=[assigned_driver_id])
    assigned_vehicle: Mapped[Vehicle | None] = relationship(foreign_keys=[assigned_vehicle_id])


class Announcement(Base):
    """spec sections 9/18: a notice for drivers and/or families --
    covers "Messages from dispatch" (section 9), and "Transportation
    announcements" / "Delay notifications" / "Bus substitution
    notices" / "Route-change notices" (section 18).

    **Almost always human-authored, with one narrow, principled
    exception**: this system has no ETA-calculation engine (no route
    geometry exists to compute one against, ADR 0001), so a "delay"
    category notice always means a dispatcher chose to tag a message
    that way, never an automatic detection. The one exception is
    "substitution": when a genuine driver/vehicle swap happens on a
    crew with an already-solved assignment (spec section 13), and the
    affected school+date+direction is unambiguous (exactly one Run,
    the same "don't guess" rule PR #23's expected-riders and
    `GET /students/{id}/bus-position` already established), this system
    auto-generates a family-facing substitution notice -- see
    `routers/announcements._maybe_create_substitution_announcement`.
    When that affected leg is ambiguous, nothing is auto-generated; a
    dispatcher can still post one manually.

    `school_id` scopes an announcement to one school's families (null
    means district-wide) -- meaningless for `audience=driver`, since a
    driver isn't tied to one school, so it's ignored for that
    audience."""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    category: Mapped[AnnouncementCategory] = mapped_column(
        SAEnum(AnnouncementCategory, native_enum=False, length=20),
        default=AnnouncementCategory.GENERAL,
        nullable=False,
    )
    audience: Mapped[AnnouncementAudience] = mapped_column(
        SAEnum(AnnouncementAudience, native_enum=False, length=10), nullable=False
    )
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    school: Mapped[School | None] = relationship()


class OptimizationSettings(Base):
    """Administrator-configured soft-objective weights (spec section
    2.2). A singleton: at most one row, id fixed at 1, absent = the
    solver's defaults. Weights only rank feasible schedules; they never
    relax a hard constraint."""

    __tablename__ = "optimization_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    crews_used_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deadhead_minutes_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    arrival_buffer_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


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


class RevokedToken(Base):
    """A JWT `jti` revoked before its natural expiry (ADR 0006 follow-up:
    POST /auth/logout actually invalidates the token server-side, not
    just the browser's cookie). `expires_at` mirrors the token's own
    `exp` claim, so a revoked-and-now-naturally-expired row can be
    opportunistically pruned (see security.revoke_token) without a
    separate scheduled job."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
