from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from isd_api.models import (
    AbsenceReason,
    AssignmentStatus,
    QualificationKind,
    RideDirection,
    RidershipDefault,
    Role,
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
    qualification_codes: list[str] = Field(default_factory=list)


class VehicleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    nominal_capacity: int | None
    effective_capacity: int | None
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


class RunCreate(BaseModel):
    service_date: date
    school_id: int
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
    window_earliest: int
    window_latest: int
    duration_minutes: int
    buffer_minutes: int
    passenger_count: int
    required_qualifications: list[QualificationRead]


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
            "This is not bus-legal routing — see docs/adr/0006."
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


class SubstituteCandidate(BaseModel):
    driver_id: int
    full_name: str
    score: int
    reasons: list[str]


class AffectedAssignmentSubstitutes(BaseModel):
    """spec section 13.1: one of the absent driver's assignments for
    the date, plus ranked substitute candidates and the vehicle that
    would need re-pairing (POST /crews) with whichever candidate is
    chosen — completing a substitution reuses that existing endpoint
    plus PATCH /schedule/assignments/{id}, not a new one."""

    assignment_id: int
    run_id: int
    school_name: str
    start_minute: int
    end_minute: int
    vehicle_id: int
    vehicle_label: str
    candidates: list[SubstituteCandidate]
