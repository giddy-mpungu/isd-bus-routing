from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from isd_api.models import (
    AbsenceReason,
    AnnouncementAudience,
    AnnouncementCategory,
    AssignmentStatus,
    DriverReportType,
    GeographicKnowledgeCategory,
    QualificationKind,
    RestrictedVehicleDimension,
    RideDirection,
    RidershipDefault,
    Role,
    TripStatus,
)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    role: Role
    driver_id: int | None = None
    school_id: int | None = None
    student_id: int | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    driver_id: int | None = None
    school_id: int | None = None
    student_id: int | None = None


class QualificationCreate(BaseModel):
    code: str
    kind: QualificationKind
    description: str | None = None


class QualificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    kind: QualificationKind
    description: str | None = None


class SchoolCreate(BaseModel):
    name: str
    location_lat: float = Field(ge=-90, le=90)
    location_lon: float = Field(ge=-180, le=180)


class SchoolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    location_lat: float
    location_lon: float


class VehicleCreate(BaseModel):
    label: str
    nominal_capacity: int | None = Field(default=None, gt=0)
    effective_capacity: int | None = Field(default=None, gt=0)
    length_m: float | None = Field(default=None, gt=0)
    width_m: float | None = Field(default=None, gt=0)
    height_m: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    qualification_codes: list[str] = Field(default_factory=list)


class VehicleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    nominal_capacity: int | None
    effective_capacity: int | None
    length_m: float | None
    width_m: float | None
    height_m: float | None
    weight_kg: float | None
    qualifications: list[QualificationRead]


class DriverCreate(BaseModel):
    full_name: str
    max_continuous_minutes: int | None = Field(default=None, gt=0)
    qualification_codes: list[str] = Field(default_factory=list)


class DriverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    max_continuous_minutes: int | None
    qualifications: list[QualificationRead]


class CrewCreate(BaseModel):
    service_date: date
    driver_id: int
    vehicle_id: int
    available_window_earliest: int = Field(ge=0, lt=1440)
    available_window_latest: int = Field(ge=0, lt=1440)


class CrewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    service_date: date
    driver_id: int
    vehicle_id: int
    available_window_earliest: int
    available_window_latest: int


class CrewDriverUpdate(BaseModel):
    driver_id: int


class RunCreate(BaseModel):
    service_date: date
    school_id: int
    direction: RideDirection
    window_earliest: int = Field(ge=0, lt=1440)
    window_latest: int = Field(ge=0, lt=1440)
    duration_minutes: int = Field(gt=0)
    buffer_minutes: int = Field(ge=0, default=0)
    passenger_count: int = Field(ge=0, default=0)
    required_qualification_codes: list[str] = Field(default_factory=list)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    service_date: date
    school_id: int
    direction: RideDirection
    window_earliest: int
    window_latest: int
    duration_minutes: int
    buffer_minutes: int
    passenger_count: int
    required_qualifications: list[QualificationRead]


class RunUpdate(BaseModel):
    passenger_count: int | None = Field(default=None, ge=0)


class ExpectedRidersRead(BaseModel):
    expected_passenger_count: int
    ambiguous: bool
    riding_student_names: list[str]


class ObservedRunDurationRead(BaseModel):
    """spec section 20: historical learning, applied to Run.duration_minutes.
    See routers/runs.py's get_observed_run_duration for how this is
    computed entirely from data already persisted -- no new history
    table."""

    sample_count: int
    average_actual_minutes: float | None
    most_recent_actual_minutes: int | None
    most_recent_service_date: date | None


class AssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    crew_id: int
    start_minute: int
    end_minute: int
    explanation_text: str
    locked: bool


class AssignmentUpdate(BaseModel):
    """Partial update — only fields provided are changed. Every hard
    constraint the solver enforces (qualification, capacity, no
    overlap, window bounds) is re-checked server-side regardless of
    which fields are provided (spec section 21 human override must
    still respect true hard constraints — see routers/schedule.py)."""

    crew_id: int | None = None
    start_minute: int | None = Field(default=None, ge=0, lt=1440)
    end_minute: int | None = Field(default=None, ge=0, lt=1440)
    locked: bool | None = None


class AssignmentStatusUpdate(BaseModel):
    """Driver-reported progress on their own assignment (Phase 4) —
    distinct from AssignmentUpdate, which is the dispatcher-only
    scheduling override."""

    status: AssignmentStatus


class DriverAssignmentRead(BaseModel):
    """Denormalized view of an assignment for the driver who's working
    it — resolved school/vehicle names instead of raw ids, since a
    driver has no other endpoint available to look those up (spec
    section 17 least-privilege; see routers/schedule.py)."""

    id: int
    run_id: int
    service_date: date
    school_name: str
    vehicle_label: str
    start_minute: int
    end_minute: int
    status: AssignmentStatus
    locked: bool


class ScheduleRequest(BaseModel):
    service_date: date
    average_deadhead_speed_kmh: float = Field(
        default=30.0,
        gt=0,
        description=(
            "Straight-line deadhead approximation speed (Phase 1 estimator). "
            "Used directly when no ISD_API_ORS_API_KEY is configured; when one "
            "is, this instead serves as the fallback speed if the "
            "OpenRouteService routing call fails (see isd_api.config.settings, "
            "isd_solver.domain.ors_deadhead_estimator). This is not full "
            "bus-legal routing — see docs/adr/0007."
        ),
    )


class ScheduleResult(BaseModel):
    crews_used: int
    assignments: list[AssignmentRead]


class ScheduleInfeasible(BaseModel):
    feasible: bool = False
    reason: str


class StopCreate(BaseModel):
    label: str
    location_lat: float = Field(ge=-90, le=90)
    location_lon: float = Field(ge=-180, le=180)


class StopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    location_lat: float
    location_lon: float


class StudentCreate(BaseModel):
    full_name: str
    school_id: int
    stop_id: int | None = None
    default_ridership: RidershipDefault = RidershipDefault.RIDES


class StudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    school_id: int
    stop_id: int | None
    default_ridership: RidershipDefault


class StudentUpdate(BaseModel):
    """Partial update — only fields provided are changed."""

    stop_id: int | None = None
    default_ridership: RidershipDefault | None = None


class GuardianLink(BaseModel):
    user_id: int


class RidershipOverrideUpdate(BaseModel):
    """spec section 4.2 daily override / section 4.5 late request to
    ride — both use this same shape, upserted by (student_id,
    service_date, direction)."""

    service_date: date
    direction: RideDirection
    is_riding: bool


class FamilyMemberRead(BaseModel):
    """Denormalized view of one linked child for a student/parent's own
    'my family' read — resolved names instead of raw ids, mirroring
    DriverAssignmentRead's reasoning (spec section 18 least-privilege:
    a student/parent has no other endpoint to look these up, and must
    never see another family's data)."""

    student_id: int
    full_name: str
    school_name: str
    stop_label: str | None
    service_date: date
    riding_am: bool
    riding_pm: bool


class AbsenceCreate(BaseModel):
    service_date: date
    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(ge=0, lt=1440)
    reason: AbsenceReason


class AbsenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    driver_id: int
    service_date: date
    start_minute: int
    end_minute: int
    reason: AbsenceReason


class DriverReportCreate(BaseModel):
    service_date: date
    report_type: DriverReportType
    description: str = Field(min_length=1, max_length=1000)


class DriverReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    driver_id: int
    vehicle_id: int | None
    service_date: date
    report_type: DriverReportType
    description: str
    created_at: datetime


class GeographicKnowledgeOverrideCreate(BaseModel):
    location_lat: float = Field(ge=-90, le=90)
    location_lon: float = Field(ge=-180, le=180)
    category: GeographicKnowledgeCategory
    note: str = Field(min_length=1, max_length=1000)
    # Required together, and only meaningful, for category=congestion_window
    # -- see routers/geographic_knowledge.py for the per-category
    # validation (same "validate at the router" precedent as FieldTrip's
    # departure/return checks, not a schema-level model_validator).
    window_start_minute: int | None = Field(default=None, ge=0, le=1439)
    window_end_minute: int | None = Field(default=None, ge=0, le=1439)
    # Required together, and only meaningful, for category=vehicle_size_restricted.
    restricted_dimension: RestrictedVehicleDimension | None = None
    max_allowed_value: float | None = Field(default=None, gt=0)
    # Required, and only meaningful, for category=preferred_entrance -- says
    # which school's regular runs should route to this override's own
    # location_lat/location_lon instead of the school's own centroid.
    school_id: int | None = None


class GeographicKnowledgeOverrideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    location_lat: float
    location_lon: float
    category: GeographicKnowledgeCategory
    note: str
    window_start_minute: int | None
    window_end_minute: int | None
    restricted_dimension: RestrictedVehicleDimension | None
    max_allowed_value: float | None
    school_id: int | None
    created_at: datetime


class SubstituteCandidate(BaseModel):
    driver_id: int
    full_name: str
    score: int
    reasons: list[str]


class PositionUpdate(BaseModel):
    """ADR 0009: a driver tablet's periodic position ping."""

    service_date: date
    location_lat: float = Field(ge=-90, le=90)
    location_lon: float = Field(ge=-180, le=180)
    recorded_at: datetime


class VehiclePositionRead(BaseModel):
    """Denormalized fleet-view row (dispatcher/transportation_admin,
    spec section 17's "GPS fleet view") -- resolved driver/vehicle
    names, mirroring DriverAssignmentRead's reasoning."""

    crew_id: int
    driver_id: int
    driver_full_name: str
    vehicle_id: int
    vehicle_label: str
    location_lat: float
    location_lon: float
    recorded_at: datetime


class BusPositionRead(BaseModel):
    """spec section 18: a family's "approximate bus location" for one
    child's leg. Deliberately decision-support-shaped like
    ExpectedRidersRead (PR #23): `available=False` covers every reason
    there's nothing to show yet (no run, no assignment, no position
    reported), and `ambiguous=True` -- the same multi-run-per-leg gap
    PR #23 named -- means this system can't yet tell which of several
    runs serves this child, so it deliberately shows nothing rather
    than guessing."""

    available: bool
    ambiguous: bool
    location_lat: float | None = None
    location_lon: float | None = None
    recorded_at: datetime | None = None
    driver_full_name: str | None = None
    vehicle_label: str | None = None


class DestinationProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    location_lat: float | None = Field(default=None, ge=-90, le=90)
    location_lon: float | None = Field(default=None, ge=-180, le=180)
    approved_entrance: str | None = Field(default=None, max_length=500)
    parking_notes: str | None = Field(default=None, max_length=500)
    turn_restrictions: str | None = Field(default=None, max_length=500)
    driver_notes: str | None = Field(default=None, max_length=1000)


class DestinationProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    location_lat: float | None
    location_lon: float | None
    approved_entrance: str | None
    parking_notes: str | None
    turn_restrictions: str | None
    driver_notes: str | None
    created_at: datetime


class FieldTripCreate(BaseModel):
    """spec section 12. Supports multi-day (overnight) trips -- see
    routers/field_trips.py's `_daily_windows` for how conflict
    detection handles a trip spanning more than one calendar date."""

    requesting_party: str = Field(min_length=1, max_length=255)
    origin: str = Field(min_length=1, max_length=255)
    destination: str = Field(min_length=1, max_length=255)
    destination_profile_id: int | None = None
    departure_at: datetime
    expected_return_at: datetime
    passenger_count: int = Field(ge=0, default=0)
    trip_contact: str = Field(min_length=1, max_length=255)
    bus_assistant_name: str | None = None
    special_instructions: str | None = Field(default=None, max_length=1000)
    required_qualification_codes: list[str] = Field(default_factory=list)


class FieldTripRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    requesting_party: str
    origin: str
    destination: str
    destination_profile_id: int | None
    destination_profile: DestinationProfileRead | None
    departure_at: datetime
    expected_return_at: datetime
    actual_return_at: datetime | None
    passenger_count: int
    assigned_driver_id: int | None
    assigned_vehicle_id: int | None
    bus_assistant_name: str | None
    trip_contact: str
    special_instructions: str | None
    status: TripStatus
    required_qualifications: list[QualificationRead]


class FieldTripUpdate(BaseModel):
    """Partial update -- only fields provided are changed. Assigning a
    driver/vehicle here does NOT re-check conflicts automatically;
    call GET .../conflicts first (spec section 12.1/12.2 -- see
    routers/field_trips.py for why this is one read endpoint, not a
    separate "delay management" mechanism)."""

    status: TripStatus | None = None
    assigned_driver_id: int | None = None
    assigned_vehicle_id: int | None = None
    destination_profile_id: int | None = None
    expected_return_at: datetime | None = None
    actual_return_at: datetime | None = None


class FieldTripConflictCheck(BaseModel):
    conflicts: list[str]


class FieldTripObservedDurationRead(BaseModel):
    """spec section 20 applied to field trips: like
    ObservedRunDurationRead, but a completed FieldTrip already stores
    its own actual start/end (departure_at, actual_return_at) directly
    -- no audit-log lookup needed, since (unlike a regular Assignment)
    that data was never split across separate status-change events."""

    sample_count: int
    average_actual_minutes: float | None
    most_recent_actual_minutes: int | None
    most_recent_departure_date: date | None


class AnnouncementCreate(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    category: AnnouncementCategory = AnnouncementCategory.GENERAL
    audience: AnnouncementAudience
    school_id: int | None = None


class AnnouncementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    message: str
    category: AnnouncementCategory
    audience: AnnouncementAudience
    school_id: int | None
    created_at: datetime


class AffectedAssignmentSubstitutes(BaseModel):
    """spec section 13.1: one of the absent driver's assignments for
    the date, plus ranked substitute candidates. `crew_id` is the
    absent driver's own crew (same vehicle, same date) — a candidate
    with no crew of their own that date gets substituted in by
    repointing *this* crew's driver (PATCH /crews/{crew_id}), not by
    creating a second crew for the same vehicle+date, which the
    vehicle's own uniqueness constraint would reject. A candidate who
    already has a different crew that date is reassigned via the
    existing PATCH /schedule/assignments/{id} instead."""

    assignment_id: int
    run_id: int
    school_name: str
    start_minute: int
    end_minute: int
    crew_id: int
    vehicle_id: int
    vehicle_label: str
    candidates: list[SubstituteCandidate]
