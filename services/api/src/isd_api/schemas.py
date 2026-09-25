from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from isd_api.models import (
    AbsenceReason,
    AnnouncementAudience,
    AnnouncementCategory,
    AssignmentStatus,
    DriverReportType,
    GeographicKnowledgeCategory,
    LicenseClass,
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
    created_at: datetime


class UserUpdate(BaseModel):
    """spec section 17: "user permissions" — role reassignment and
    deactivation. Deliberately does NOT cover email or password: this
    system has no password-reset flow, and changing another user's
    email/password is a materially more security-sensitive action than
    anything else this endpoint does; a user's own credentials stay
    self-service (there is none yet) or an admin re-creates the
    account, not silently overwritten here."""

    role: Role | None = None
    is_active: bool | None = None
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
    is_active: bool = True


class QualificationUpdate(BaseModel):
    """`code`/`kind` are deliberately not editable here — many-to-many
    rows reference a qualification by id, not by code, so this is a
    scope choice (avoid a code meaning something different than what a
    driver/vehicle was actually granted), not a technical limit."""

    description: str | None = None
    is_active: bool | None = None


class SchoolCreate(BaseModel):
    name: str
    location_lat: float = Field(ge=-90, le=90)
    location_lon: float = Field(ge=-180, le=180)
    external_id: str | None = Field(default=None, min_length=1, max_length=64)


class SchoolUpdate(BaseModel):
    """Every field optional; only fields actually sent are changed. An
    explicit null for external_id clears the SIS mapping (as before)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    location_lat: float | None = Field(default=None, ge=-90, le=90)
    location_lon: float | None = Field(default=None, ge=-180, le=180)
    external_id: str | None = Field(default=None, min_length=1, max_length=64)


class SchoolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    location_lat: float
    location_lon: float
    external_id: str | None = None


class VehicleCreate(BaseModel):
    label: str
    nominal_capacity: int | None = Field(default=None, gt=0)
    effective_capacity: int | None = Field(default=None, gt=0)
    length_m: float | None = Field(default=None, gt=0)
    width_m: float | None = Field(default=None, gt=0)
    height_m: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    qualification_codes: list[str] = Field(default_factory=list)
    # None = infer from capacity (15+ passengers needs CDL B).
    required_license_class: LicenseClass | None = None


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
    required_license_class: LicenseClass
    is_active: bool = True
    qualifications: list[QualificationRead]


class VehicleUpdate(BaseModel):
    """Partial update, same convention as StudentUpdate — only provided
    fields change. A nullable field (e.g. length_m) can be set but not
    explicitly cleared back to null this way, matching that existing
    convention's own limit."""

    label: str | None = Field(default=None, min_length=1)
    nominal_capacity: int | None = Field(default=None, gt=0)
    effective_capacity: int | None = Field(default=None, gt=0)
    length_m: float | None = Field(default=None, gt=0)
    width_m: float | None = Field(default=None, gt=0)
    height_m: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    required_license_class: LicenseClass | None = None
    qualification_codes: list[str] | None = None
    is_active: bool | None = None


class DriverCreate(BaseModel):
    full_name: str
    max_continuous_minutes: int | None = Field(default=None, gt=0)
    qualification_codes: list[str] = Field(default_factory=list)
    # None = take it from a license code in qualification_codes (e.g.
    # "CDL_B"), else not on record, which qualifies for no vehicle.
    license_class: LicenseClass | None = None


class DriverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    max_continuous_minutes: int | None
    license_class: LicenseClass | None = None
    is_active: bool = True
    qualifications: list[QualificationRead]


class DriverUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1)
    max_continuous_minutes: int | None = Field(default=None, gt=0)
    qualification_codes: list[str] | None = None
    is_active: bool | None = None
    # Sent as null, clears the class (the driver then qualifies for nothing).
    license_class: LicenseClass | None = None


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


def _validate_days_of_week(value: list[int]) -> list[int]:
    if not value:
        raise ValueError("days_of_week must contain at least one weekday")
    if any(d < 0 or d > 6 for d in value):
        raise ValueError("days_of_week values must be 0 (Monday) through 6 (Sunday)")
    if len(set(value)) != len(value):
        raise ValueError("days_of_week must not contain duplicates")
    return sorted(value)


class RouteTemplateCreate(BaseModel):
    school_id: int
    direction: RideDirection
    window_earliest: int = Field(ge=0, lt=1440)
    window_latest: int = Field(ge=0, lt=1440)
    duration_minutes: int = Field(gt=0)
    buffer_minutes: int = Field(ge=0, default=0)
    days_of_week: list[int]
    active_from: date | None = None
    active_until: date | None = None
    required_qualification_codes: list[str] = Field(default_factory=list)

    @field_validator("days_of_week")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        return _validate_days_of_week(value)


class RouteTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    school_id: int
    direction: RideDirection
    window_earliest: int
    window_latest: int
    duration_minutes: int
    buffer_minutes: int
    days_of_week: list[int]
    active_from: date | None
    active_until: date | None
    is_active: bool
    required_qualifications: list[QualificationRead]


class CrewTemplateCreate(BaseModel):
    driver_id: int
    vehicle_id: int
    available_window_earliest: int = Field(ge=0, lt=1440)
    available_window_latest: int = Field(ge=0, lt=1440)
    days_of_week: list[int]
    active_from: date | None = None
    active_until: date | None = None

    @field_validator("days_of_week")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        return _validate_days_of_week(value)


class CrewTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    driver_id: int
    vehicle_id: int
    available_window_earliest: int
    available_window_latest: int
    days_of_week: list[int]
    active_from: date | None
    active_until: date | None
    is_active: bool


class TemplateUpdate(BaseModel):
    """Shared by route and crew templates: deactivating/reactivating is
    the only edit supported. Changing a template's contents means
    creating a new one and deactivating the old, so past generated days
    stay traceable to exactly what generated them."""

    is_active: bool


class GenerateFromTemplatesRead(BaseModel):
    service_date: date
    runs_created: int
    runs_already_existing: int
    crews_created: int
    crews_already_existing: int
    # Driver ids skipped because an absence fully covers the crew
    # template's window that day (spec section 13; substitutes are the
    # absences workflow's job, not generation's).
    crews_skipped_absent_driver_ids: list[int]
    # Crew template ids skipped because the template's vehicle is out of
    # service or its driver is deactivated (spec section 2.1).
    crews_skipped_out_of_service_template_ids: list[int]
    # Crew template ids skipped because the driver isn't licensed for the
    # template's vehicle (spec section 15).
    crews_skipped_unlicensed_template_ids: list[int]


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
    status: AssignmentStatus = AssignmentStatus.SENT
    # Set when the crew became unavailable after this assignment was made
    # (driver absent or deactivated, vehicle out of service), e.g. a locked
    # assignment a re-solve deliberately left in place. None when fine.
    availability_issue: str | None = None


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
    # Dispatch may set any lifecycle state, e.g. to correct a driver's mistake.
    status: AssignmentStatus | None = None


class AssignmentStatusUpdate(BaseModel):
    """Driver-reported progress on their own assignment (Phase 4) —
    distinct from AssignmentUpdate, which is the dispatcher-only
    scheduling override."""

    status: AssignmentStatus


class AssignmentStopRoster(BaseModel):
    """One stop's worth of expected riders for a driver's assignment
    (spec section 9: "Stops", "Authorized student information").
    Deliberately an UNORDERED grouping, not a sequenced/optimized stop
    order — this system has no stop-sequence model (see
    docs/domain-model.md's "Not yet implemented", spec section 4.3's
    same scope boundary). `stop_label` is None for students with no
    `stop_id` set, grouped together rather than dropped."""

    stop_label: str | None
    student_names: list[str]


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
    # spec section 21 "don't guess": True when more than one Run shares
    # this run's (school_id, service_date, direction) — same ambiguity
    # rule as GET /runs/{id}/expected-riders. `stops` is always empty
    # when this is True; the driver app shows a note instead of a
    # possibly-wrong roster.
    roster_ambiguous: bool
    stops: list[AssignmentStopRoster]


class SchoolAssignmentRead(BaseModel):
    """Denormalized view of an assignment for a school_admin viewing
    their own school's buses -- spec section 17: "buses serving the
    school" / "expected arrivals." Resolved driver/vehicle names for
    the same least-privilege reason as DriverAssignmentRead (school_admin
    has no other endpoint that can look up GET /drivers or /crews)."""

    id: int
    run_id: int
    service_date: date
    direction: RideDirection
    window_earliest: int
    window_latest: int
    driver_full_name: str
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


class RidershipRulesBase(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    am_cutoff_minute: int | None = Field(default=None, ge=0, lt=1440)
    pm_cutoff_minute: int | None = Field(default=None, ge=0, lt=1440)

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}; use an IANA name") from exc
        return value


class RidershipRulesUpdate(RidershipRulesBase):
    pass


class RidershipRulesRead(RidershipRulesBase):
    is_default: bool


class OptimizationSettingsBase(BaseModel):
    crews_used_weight: int = Field(ge=0, le=1000)
    deadhead_minutes_weight: int = Field(ge=0, le=1000)
    arrival_buffer_weight: int = Field(ge=0, le=1000)
    # Spec section 16: minimum spare minutes between consecutive runs on
    # one crew, after travel. A hard constraint, not a weight: a schedule
    # that can't meet it is rejected rather than built tight.
    minimum_buffer_minutes: int = Field(default=0, ge=0, le=120)

    @model_validator(mode="after")
    def _at_least_one_positive(self) -> OptimizationSettingsBase:
        if not (
            self.crews_used_weight or self.deadhead_minutes_weight or self.arrival_buffer_weight
        ):
            raise ValueError("at least one objective weight must be greater than zero")
        return self


class OptimizationSettingsUpdate(OptimizationSettingsBase):
    pass


class OptimizationSettingsRead(OptimizationSettingsBase):
    # False when nothing has been saved yet and the solver defaults apply.
    is_default: bool


class ScheduleResult(BaseModel):
    crews_used: int
    assignments: list[AssignmentRead]
    # Exact totals for the schedule just solved; None when nothing was
    # solved this call (everything already locked).
    total_deadhead_minutes: int | None = None
    total_arrival_buffer_minutes: int | None = None


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


class StopUpdate(BaseModel):
    """spec section 3.1/21: "relocate" a stop — edits its label and/or
    coordinates. No is_active/deactivate here: a Stop with no student
    referencing it can just be deleted outright (DELETE /stops/{id});
    one still in use can't be relocated out from under a student
    silently, but it can always be edited to the correct location."""

    label: str | None = Field(default=None, min_length=1)
    location_lat: float | None = Field(default=None, ge=-90, le=90)
    location_lon: float | None = Field(default=None, ge=-180, le=180)


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
    external_id: str | None = None
    stop_id: int | None
    default_ridership: RidershipDefault


class StudentUpdate(BaseModel):
    """Every field optional; only fields actually sent are changed, and an
    explicit null for stop_id clears the stop. full_name and school_id are
    refused for a student imported from the SIS (external_id set): the SIS
    is the authoritative source for those (ADR 0007)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    school_id: int | None = None
    stop_id: int | None = None
    default_ridership: RidershipDefault | None = None


class GuardianLink(BaseModel):
    user_id: int


class GuardianRead(BaseModel):
    user_id: int
    full_name: str
    email: str


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
    # Spec section 4.4: set when the family can no longer change that leg
    # (a past day, or today after the district's cutoff), with the reason.
    am_changes_closed: str | None = None
    pm_changes_closed: str | None = None


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
    than guessing.

    Deliberately carries no driver identity (spec section 18), and the
    coordinates are rounded to roughly 100 m ("approximate")."""

    available: bool
    ambiguous: bool
    location_lat: float | None = None
    location_lon: float | None = None
    recorded_at: datetime | None = None
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
    # The subset of `conflicts` that are regular routes the trip takes the
    # driver or bus away from. They don't block assignment; each is
    # flagged "needs cover" on the schedule instead (spec section 12.2).
    routes_needing_cover: list[str] = []
    # Minutes held before departure and after return (pre/post-trip).
    turnaround_minutes: int = 0


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


class AuditLogEntryRead(BaseModel):
    """spec section 17/21: the audit trail made readable. actor_full_name
    is resolved by the router (models.AuditLogEntry deliberately has no
    ORM relationship back to User), null for a system-initiated entry
    with no actor. before_state/after_state are whatever JSON-serializable
    dict the writing router passed to isd_api.audit.record -- shape
    varies by entity_type, not a fixed schema."""

    id: int
    entity_type: str
    entity_id: int
    action: str
    actor_user_id: int | None
    actor_full_name: str | None
    before_state: dict | None
    after_state: dict | None
    created_at: datetime


class SisImportRow(BaseModel):
    line: int
    source_id: str | None
    full_name: str | None
    # created | updated | unchanged | linked | needs_review | removal_requested | error
    action: str
    detail: str | None = None
    student_id: int | None = None


class SisImportResult(BaseModel):
    dry_run: bool
    counts: dict[str, int]
    # Rows that are not "unchanged", capped; counts above are always complete.
    rows: list[SisImportRow]
    rows_truncated: bool
    ignored_non_student_rows: int
