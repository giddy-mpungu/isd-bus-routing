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
from sqlalchemy import (
    false as sa_false,
)
from sqlalchemy import (
    true as sa_true,
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


class RouteKind(enum.StrEnum):
    """Spec section 11's kinds of route: the everyday ones, and special
    education assignments, activity routes and shuttles."""

    REGULAR = "regular"
    SPECIAL_EDUCATION = "special_education"
    ACTIVITY = "activity"
    SHUTTLE = "shuttle"


class TripKind(enum.StrEnum):
    """Spec section 11's kinds of trip: field trips, athletic trips and
    activity trips."""

    FIELD_TRIP = "field_trip"
    ATHLETIC = "athletic"
    ACTIVITY = "activity"
    OTHER = "other"


# Spec section 16's reasons for a route's buffer, in the order shown.
BUFFER_FACTORS = (
    "traffic",
    "loading",
    "wheelchair",
    "weather",
    "rail_crossings",
    "pre_trip",
    "fueling",
    "other",
)


class VehicleType(enum.StrEnum):
    """Spec section 6's vehicle type: the US school bus types (A smallest,
    on a van chassis, to D, a transit-style bus), or a van or other."""

    TYPE_A = "type_a"
    TYPE_B = "type_b"
    TYPE_C = "type_c"
    TYPE_D = "type_d"
    VAN = "van"
    OTHER = "other"


class LicenseClass(enum.StrEnum):
    """Spec section 1: "class A & B CDL, and Class C Non-CDL Drivers".
    Tiered; see isd_api/licensing.py."""

    CDL_A = "cdl_a"
    CDL_B = "cdl_b"
    CLASS_C = "class_c"


class AssignmentStatus(enum.StrEnum):
    """Spec section 14's lifecycle; see isd_api/assignment_states.py."""

    SENT = "sent"
    RECEIVED = "received"
    ACKNOWLEDGED = "acknowledged"
    EN_ROUTE = "en_route"
    ARRIVED = "arrived"
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


class DispatchTaskKind(enum.StrEnum):
    """Spec section 14's unplanned assignments dispatch can issue."""

    COVER_ROUTE = "cover_route"
    ASSIST_DISABLED_BUS = "assist_disabled_bus"
    TRANSFER_PASSENGERS = "transfer_passengers"
    RETURN_TO_SCHOOL = "return_to_school"
    MOVE_VEHICLE = "move_vehicle"
    ASSIST_DRIVER = "assist_driver"
    EMERGENCY = "emergency"
    OTHER = "other"


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
    # A vehicle capability whose students ride in their wheelchair, so each
    # takes one of the bus's wheelchair positions (spec section 6).
    takes_wheelchair_position: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
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
    # Bumped whenever the password changes: every token carries the value
    # it was issued under (claim "tv"), so a change or reset signs the
    # account out everywhere else (security.get_current_user).
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # Two-step sign-in (isd_api/mfa.py): the authenticator secret,
    # encrypted; a secret being set up but not yet confirmed; the time
    # step of the last code accepted, so no code works twice.
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_pending_secret_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Single sign-on (isd_api/oidc.py): the provider's id for this person,
    # set at their first SSO sign-in; later ones must match it.
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    # Bus-time emails (isd_api/eta_notifications.py): on unless turned off.
    eta_emails_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sa_true(), nullable=False
    )
    # The language they chose for screens and emails (isd_api/i18n), or
    # None if they never chose: emails are then in English.
    preferred_language: Mapped[str | None] = mapped_column(String(8), nullable=True)

    driver: Mapped[Driver | None] = relationship(back_populates="user")

    @property
    def sso_linked(self) -> bool:
        return self.oidc_subject is not None

    @property
    def mfa_enabled(self) -> bool:
        return self.mfa_secret_encrypted is not None

    @property
    def mfa_required(self) -> bool:
        # Never on driver accounts: tablets are shared (isd_api/mfa.py).
        from isd_api.config import settings

        return self.role != Role.DRIVER and self.role.value in settings.mfa_required_roles

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
    # This school's own bus windows around its bells (isd_api/bells.py),
    # in minutes; None = the district's (BellRules).
    arrive_earliest_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    arrive_latest_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leave_earliest_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leave_latest_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Spec section 3's attendance zone: the school's boundary from the
    # district's GIS, a GeoJSON Polygon or MultiPolygon (isd_api/zones.py).
    zone_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    runs: Mapped[list[Run]] = relationship(back_populates="school")

    @property
    def has_zone(self) -> bool:
        return self.zone_geojson is not None

    bell_schedules: Mapped[list[BellSchedule]] = relationship(
        back_populates="school", order_by="BellSchedule.name", cascade="all, delete-orphan"
    )


class BellSchedule(Base):
    """A school's bell times (spec sections 1, 5, 19): its Regular day and
    named alternates (Early release, Late start, ...). Exactly one per
    school is the regular one, used on any day the calendar doesn't name
    another. Minutes of the day, in the district's time zone."""

    __tablename__ = "bell_schedules"
    __table_args__ = (UniqueConstraint("school_id", "name", name="uq_bell_schedule_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    first_bell_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    dismissal_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    is_regular: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    school: Mapped[School] = relationship(back_populates="bell_schedules")


class BellCalendarDay(Base):
    """A date on which a school uses a schedule other than its regular one
    (an early-release or late-start day)."""

    __tablename__ = "bell_calendar_days"
    __table_args__ = (UniqueConstraint("school_id", "service_date", name="uq_bell_calendar_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    bell_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("bell_schedules.id", ondelete="CASCADE"), nullable=False
    )

    schedule: Mapped[BellSchedule] = relationship()


class BellRules(Base):
    """The district's bus windows around school bells (isd_api/bells.py).
    A singleton: at most one row, id 1; absent = the defaults there."""

    __tablename__ = "bell_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    arrive_earliest_before: Mapped[int] = mapped_column(Integer, nullable=False)
    arrive_latest_before: Mapped[int] = mapped_column(Integer, nullable=False)
    leave_earliest_after: Mapped[int] = mapped_column(Integer, nullable=False)
    leave_latest_after: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


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
    """spec section 3. The home location lives in its own admin-only
    table (`StudentHome`), so no read that dispatchers or drivers use can
    carry it. Eligibility is worked out, not stored (isd_api/eligibility.py)."""

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
    # "PK", "K" or "1".."12" (isd_api/eligibility.py GRADES). SIS-owned for
    # imported students, like name and school.
    grade: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # Spec section 3.1 "students receiving specialized transportation":
    # always eligible, with their own walk and ride limits.
    needs_specialized_transport: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Eligible regardless of distance, because the walk to school is
    # unsafe (an admin decision, e.g. a highway with no crossing).
    hazardous_route: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # FERPA (isd_api/retention.py): the day the student left the district.
    # From then on they don't ride; their personal data is deleted after
    # the end of the following school year.
    withdrawn_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    school: Mapped[School] = relationship()
    stop: Mapped[Stop | None] = relationship()
    # What the bus must have for this student (spec section 3
    # "accommodation data"), in the same tags vehicles and runs use.
    accommodations: Mapped[list[Qualification]] = relationship(secondary="student_accommodations")
    guardians: Mapped[list[User]] = relationship(
        secondary="student_guardians", back_populates="guardian_of"
    )


student_accommodations = Table(
    "student_accommodations",
    Base.metadata,
    Column("student_id", ForeignKey("students.id"), primary_key=True),
    Column("qualification_id", ForeignKey("qualifications.id"), primary_key=True),
)


class GeocodeSource(enum.StrEnum):
    CENSUS = "census"
    MANUAL = "manual"


class StudentHome(Base):
    """A student's home location (spec section 3), for eligibility and,
    later, stop placement. Transportation admins only: dispatchers and
    drivers work with stops, never homes. `matched_address` is what the
    geocoder matched, so a wrong match is visible. The audit trail records
    that a home changed, never the address itself (audit rows can't be
    deleted, and this is personal data)."""

    __tablename__ = "student_homes"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    location_lat: Mapped[float] = mapped_column(nullable=False)
    location_lon: Mapped[float] = mapped_column(nullable=False)
    source: Mapped[GeocodeSource] = mapped_column(
        SAEnum(GeocodeSource, native_enum=False, length=16), nullable=False
    )
    matched_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class TransportationRules(Base):
    """District transportation rules for route building (spec section 3.1):
    who is eligible, and how far students may walk to a stop and how long
    they may ride, by grade band. One row (id 1); missing means the
    defaults in isd_api/eligibility.py."""

    __tablename__ = "transportation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    eligibility_miles: Mapped[float] = mapped_column(nullable=False)
    walk_miles_prek: Mapped[float] = mapped_column(nullable=False)
    walk_miles_elementary: Mapped[float] = mapped_column(nullable=False)
    walk_miles_middle: Mapped[float] = mapped_column(nullable=False)
    walk_miles_high: Mapped[float] = mapped_column(nullable=False)
    walk_miles_specialized: Mapped[float] = mapped_column(nullable=False)
    ride_minutes_prek: Mapped[int] = mapped_column(Integer, nullable=False)
    ride_minutes_elementary: Mapped[int] = mapped_column(Integer, nullable=False)
    ride_minutes_middle: Mapped[int] = mapped_column(Integer, nullable=False)
    ride_minutes_high: Mapped[int] = mapped_column(Integer, nullable=False)
    ride_minutes_specialized: Mapped[int] = mapped_column(Integer, nullable=False)
    # Spec section 3.1 "minimum preferred spacing between stops".
    min_stop_spacing_miles: Mapped[float] = mapped_column(nullable=False, default=0.1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class StopProposalKind(enum.StrEnum):
    # A new stop for a group of students.
    NEW = "new"
    # Students within walking distance of a stop that already exists.
    EXISTING = "existing"
    # A curb-to-curb stop at the home of a student with specialized
    # transportation.
    CURB = "curb"


class StopProposalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class StopProposal(Base):
    """A proposed stop (spec section 3.1) for transportation staff to
    approve, reject or relocate; see isd_api/stop_proposals.py for how
    they're made. Transportation admins only: a proposal is placed from
    students' homes, so it shows where they live. Walking distances and
    warnings are worked out when read, so a relocated proposal is judged
    where it now is."""

    __tablename__ = "stop_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    kind: Mapped[StopProposalKind] = mapped_column(
        SAEnum(StopProposalKind, native_enum=False, length=16), nullable=False
    )
    status: Mapped[StopProposalStatus] = mapped_column(
        SAEnum(StopProposalStatus, native_enum=False, length=16),
        nullable=False,
        default=StopProposalStatus.PENDING,
    )
    # The existing stop (kind EXISTING), or the stop approval created.
    stop_id: Mapped[int | None] = mapped_column(ForeignKey("stops.id"), nullable=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    location_lat: Mapped[float] = mapped_column(nullable=False)
    location_lon: Mapped[float] = mapped_column(nullable=False)
    student_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    school: Mapped[School] = relationship()
    stop: Mapped[Stop | None] = relationship()


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
    # Spec section 15: the license class needed to drive this vehicle.
    # Inferred from capacity when not given (isd_api/licensing.py).
    required_license_class: Mapped[LicenseClass] = mapped_column(
        SAEnum(LicenseClass, native_enum=False, length=16),
        nullable=False,
        default=LicenseClass.CDL_B,
    )
    # spec section 6 vehicle profile. Persisted only — not yet consumed by
    # routing (isd_solver.domain.Vehicle's own docstring names the follow-up).
    length_m: Mapped[float | None] = mapped_column(nullable=True)
    width_m: Mapped[float | None] = mapped_column(nullable=True)
    height_m: Mapped[float | None] = mapped_column(nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(nullable=True)
    # Spec section 6's vehicle profile, recorded by the district.
    vehicle_type: Mapped[VehicleType | None] = mapped_column(
        SAEnum(VehicleType, native_enum=False, length=16), nullable=True
    )
    wheelchair_positions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Recorded now; used once routing can avoid tight turns (spec section 7).
    turning_radius_m: Mapped[float | None] = mapped_column(nullable=True)
    # Where it parks overnight (spec section 2.2's fleet mileage): the
    # solver counts the drive out to its first run and back after its last.
    yard_lat: Mapped[float | None] = mapped_column(nullable=True)
    yard_lon: Mapped[float | None] = mapped_column(nullable=True)
    # A retired/out-of-service vehicle: hidden from future crew-creation
    # dropdowns, but never hard-deleted -- existing Crew/Assignment/
    # FieldTrip/CrewTemplate rows referencing it, and everything derived
    # from them (audit log, observed-duration learning), stay intact.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Fleet maintenance (isd_api/maintenance.py): when the next service is
    # due (a warning ahead of it) and the last day the inspection is valid
    # (after it, the bus isn't scheduled).
    service_due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    inspection_expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    qualifications: Mapped[list[Qualification]] = relationship(secondary=vehicle_qualifications)
    crews: Mapped[list[Crew]] = relationship(back_populates="vehicle")

    def allowable_capacity(self) -> int | None:
        return (
            self.effective_capacity
            if self.effective_capacity is not None
            else self.nominal_capacity
        )


class MaintenanceKind(enum.StrEnum):
    PLANNED = "planned"
    REPAIR = "repair"
    INSPECTION = "inspection"


class MaintenanceWindow(Base):
    """A period a bus can't run (spec sections 2.1, 12.1 "Maintenance"):
    the scheduler, generation and field-trip checks treat it as busy.
    Wall-clock times in the district's time zone, like field trips. No end
    means until someone marks it back in service."""

    __tablename__ = "maintenance_windows"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    kind: Mapped[MaintenanceKind] = mapped_column(
        SAEnum(MaintenanceKind, native_enum=False, length=16), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    # Set when the window was opened from a driver's defect report.
    driver_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("driver_reports.id"), nullable=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    vehicle: Mapped[Vehicle] = relationship()


class ServiceRecord(Base):
    """One entry in a bus's service log: what was done, when, by whom."""

    __tablename__ = "service_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    performed_on: Mapped[date] = mapped_column(Date, nullable=False)
    work: Mapped[str] = mapped_column(String(1000), nullable=False)
    performed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The district's HR number, so HR's absence exports match exactly
    # (spec section 19; isd_api/routers/absences.py import).
    employee_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # District-configured; see isd_solver.domain.Driver docstring — this
    # codebase asserts nothing about what any specific driver-hour law requires.
    max_continuous_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Spec section 15. None = not on record, which qualifies for nothing.
    license_class: Mapped[LicenseClass | None] = mapped_column(
        SAEnum(LicenseClass, native_enum=False, length=16), nullable=True
    )
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


class DefectStatus(enum.StrEnum):
    """Where a vehicle defect report stands (isd_api/maintenance.py)."""

    OPEN = "open"
    OUT_OF_SERVICE = "out_of_service"
    FIXED = "fixed"


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
    # Vehicle defects only: open until dispatch takes the bus out of
    # service or marks it fixed.
    status: Mapped[DefectStatus] = mapped_column(
        SAEnum(DefectStatus, native_enum=False, length=16),
        nullable=False,
        default=DefectStatus.OPEN,
        # Enum columns store the member's name (as every enum here does).
        server_default=DefectStatus.OPEN.name,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

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


class ClosureKind(enum.StrEnum):
    """Spec section 10's list of conditions a bus must be routed around."""

    ROAD_CLOSED = "road_closed"
    COLLISION = "collision"
    CONSTRUCTION = "construction"
    FLOODING = "flooding"
    POLICE_ACTIVITY = "police_activity"
    SEVERE_CONGESTION = "severe_congestion"
    OTHER = "other"


class RoadClosure(Base):
    """A temporary condition to route around (spec section 10 "dynamic
    rerouting"): a point with a radius, active from `starts_at` until
    `ends_at` or until someone clears it. Unlike the standing district
    knowledge in `GeographicKnowledgeOverride` (spec section 8), a closure
    is about today: an accident, a flooded underpass, a police scene.
    Directions and the scheduler's travel times avoid active closures; see
    isd_api/closures.py for which runs they affect."""

    __tablename__ = "road_closures"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[ClosureKind] = mapped_column(
        SAEnum(ClosureKind, native_enum=False, length=32), nullable=False
    )
    note: Mapped[str] = mapped_column(String(500), nullable=False)
    location_lat: Mapped[float] = mapped_column(nullable=False)
    location_lon: Mapped[float] = mapped_column(nullable=False)
    radius_m: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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
    # Spec section 16: what the buffer is for, minutes by reason
    # (BUFFER_FACTORS); when set, buffer_minutes is their sum.
    buffer_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Spec section 11. Enum columns store member names.
    kind: Mapped[RouteKind] = mapped_column(
        SAEnum(RouteKind, native_enum=False, length=24),
        nullable=False,
        default=RouteKind.REGULAR,
        server_default="REGULAR",
    )
    # Python weekday numbers: Monday=0 .. Sunday=6.
    days_of_week: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Its window comes from the school's bells for each day (isd_api/bells.py)
    # rather than the fixed window above, which then only shows the
    # regular day's.
    follows_bells: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )

    school: Mapped[School] = relationship()
    required_qualifications: Mapped[list[Qualification]] = relationship(
        secondary=route_template_required_qualifications
    )
    # The route's stops in the order the bus visits them (AM: stops, then
    # school; PM: school, then stops). Runs generated from this template
    # use it; see isd_api/routes.py.
    stops: Mapped[list[RouteStop]] = relationship(
        order_by="RouteStop.position", cascade="all, delete-orphan"
    )


class RouteStop(Base):
    """One stop on a recurring route (spec sections 3, 9 "Stops"), at a
    position in the route's order. `minutes_from_start` is the planned
    time after the run starts (optional until routing computes it, Phase
    3.4). A stop appears on a route at most once."""

    __tablename__ = "route_stops"
    __table_args__ = (
        UniqueConstraint("route_template_id", "position", name="uq_route_stop_position"),
        UniqueConstraint("route_template_id", "stop_id", name="uq_route_stop_once"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    route_template_id: Mapped[int] = mapped_column(
        ForeignKey("route_templates.id"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_id: Mapped[int] = mapped_column(ForeignKey("stops.id"), nullable=False, index=True)
    minutes_from_start: Mapped[int | None] = mapped_column(Integer, nullable=True)

    stop: Mapped[Stop] = relationship()

    @property
    def stop_label(self) -> str:
        return self.stop.label

    @property
    def location_lat(self) -> float:
        return self.stop.location_lat

    @property
    def location_lon(self) -> float:
        return self.stop.location_lon


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
    # Its route's kind (spec section 11), copied when generated.
    kind: Mapped[RouteKind] = mapped_column(
        SAEnum(RouteKind, native_enum=False, length=24),
        nullable=False,
        default=RouteKind.REGULAR,
        server_default="REGULAR",
    )
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
        default=AssignmentStatus.SENT,
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


class PositionSample(Base):
    """One GPS report from a crew's tablet, kept as history (spec sections
    9 "route progress", 20 historical data) next to `VehiclePosition`'s
    latest-only row. Kept for `settings.position_history_days`, then
    deleted (`isd_api/position_history.py`): a bus's track shows where
    students were, so it isn't kept forever."""

    __tablename__ = "position_samples"
    __table_args__ = (
        UniqueConstraint("crew_id", "recorded_at", name="uq_position_sample_crew_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_id: Mapped[int] = mapped_column(ForeignKey("crews.id"), nullable=False, index=True)
    location_lat: Mapped[float] = mapped_column(nullable=False)
    location_lon: Mapped[float] = mapped_column(nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
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
    # The school the trip leaves from and returns to, when it's one of
    # ours: gives directions a start and conflicts the drive to the next
    # run (spec section 12.1). `origin` stays the words on the request.
    origin_school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[TripKind] = mapped_column(
        SAEnum(TripKind, native_enum=False, length=16),
        nullable=False,
        default=TripKind.FIELD_TRIP,
        server_default="FIELD_TRIP",
    )
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
    origin_school: Mapped[School | None] = relationship()

    required_qualifications: Mapped[list[Qualification]] = relationship(
        secondary=field_trip_required_qualifications
    )
    assigned_driver: Mapped[Driver | None] = relationship(foreign_keys=[assigned_driver_id])
    assigned_vehicle: Mapped[Vehicle | None] = relationship(foreign_keys=[assigned_vehicle_id])


class DispatchTask(Base):
    """Spec sections 11 and 14: unplanned work dispatch sends to a driver's
    tablet (assist a disabled bus, move a vehicle, respond to an emergency).
    It's one more job in the driver's day: it follows the same lifecycle
    as a regular assignment (`isd_api/assignment_states.py`) and is busy
    time for its driver and vehicle (`isd_api/availability.py`).

    A single-day minute window, like absences and runs. `vehicle_id` is
    optional: assisting another driver may not need a bus. Cancelling
    keeps the row (and the audit trail) and frees the time."""

    __tablename__ = "dispatch_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[DispatchTaskKind] = mapped_column(
        SAEnum(DispatchTaskKind, native_enum=False, length=32), nullable=False
    )
    service_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), nullable=False)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instructions: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[AssignmentStatus] = mapped_column(
        SAEnum(AssignmentStatus, native_enum=False, length=20),
        default=AssignmentStatus.SENT,
        nullable=False,
    )
    status_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    driver: Mapped[Driver] = relationship()
    vehicle: Mapped[Vehicle | None] = relationship()


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


class RidershipRules(Base):
    """District ridership-reporting rules (spec section 4.4). A singleton:
    at most one row, id fixed at 1; absent = the defaults (the timezone
    below, and no cutoffs)."""

    __tablename__ = "ridership_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    # IANA zone for "today" and cutoff times, e.g. America/Chicago.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Chicago")
    # Minute of day after which families can no longer change that day's
    # AM / PM ridership. None = no cutoff for that leg.
    am_cutoff_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pm_cutoff_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Spec section 4.4's route lock: this many minutes before a run leaves
    # (and while it's under way), its route's stops can't be changed.
    route_lock_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


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
    # Spec section 16: a hard floor on spare time between consecutive runs
    # on one crew, after travel. 0 = no floor beyond each run's own buffer.
    minimum_buffer_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Driver work-hour rules (spec section 2.1), each off when null: the
    # district enters its own (product owner, 2026-10-19). See
    # isd_solver.WorkRules and isd_api/work_rules.py.
    max_duty_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    break_after_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    break_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_rest_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Spec section 2.2, route planning: students' minutes on the bus
    # against the bus's own minutes (0 = the fastest route).
    ride_time_weight: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Spec section 2.2, proposing stops: shorter walks against fewer stops
    # (0 = walk up to each grade's limit; 10 = half of it).
    walking_weight: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
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


class RecordCorrection(Base):
    """A family's request to correct a student's record (FERPA's right to
    request amendment; routers/corrections.py): what's wrong, what it
    should say, and the district's decision."""

    __tablename__ = "record_corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False, index=True)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    what_is_wrong: Mapped[str] = mapped_column(String(1000), nullable=False)
    should_say: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # open | accepted | declined
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class StudentAccess(Base):
    """A staff member saw a student's information (FERPA; isd_api/access_log.py):
    once per person, student, kind of view and day, with the first time."""

    __tablename__ = "student_access_log"
    __table_args__ = (
        UniqueConstraint("student_id", "user_id", "what", "day", name="uq_student_access_daily"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    what: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SisSyncRun(Base):
    """One run of the SIS roster sync (isd_api/sis_sync.py): when, how it
    went, the counts, and the rows that wait for a person. A scheduled run
    is unique per district day (`scheduled_for`); manual ones leave it null."""

    __tablename__ = "sis_sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # scheduled | manual
    # running | ok | needs_attention | failed
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[date | None] = mapped_column(Date, unique=True, nullable=True)
    triggered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    problems: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class EtaNotification(Base):
    """One bus-time email sent to a parent (Phase 5.5): what time it gave,
    so the next one goes only when the estimate moves again. The unique
    key stops two workers sending the same email."""

    __tablename__ = "eta_notifications"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "user_id",
            "service_date",
            "direction",
            "eta_minute",
            name="uq_eta_notification_once",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[RideDirection] = mapped_column(
        SAEnum(RideDirection, native_enum=False, length=8), nullable=False
    )
    eta_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MfaRecoveryCode(Base):
    """A single-use code for signing in without the authenticator app
    (Phase 5.3). Only its SHA-256 is kept; see isd_api/mfa.py."""

    __tablename__ = "mfa_recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordResetToken(Base):
    """A one-time link to set a new password (Phase 5.1). Only the token's
    SHA-256 hash is kept; see isd_api/passwords.py."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The admin who issued it; None once self-service email resets exist.
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


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
