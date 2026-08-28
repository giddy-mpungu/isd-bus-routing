from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from isd_api.models import AssignmentStatus, QualificationKind, Role


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


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    driver_id: int | None = None
    school_id: int | None = None


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
