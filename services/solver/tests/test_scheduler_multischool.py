"""Tests for the multi-school crew scheduling solver.

test_single_crew_can_serve_all_three_bell_windows reproduces the spec
section 5 worked example: Pre-K 6:00-6:50, High School 7:00-7:50,
Middle School 8:00-9:00, and checks the solver determines one crew CAN
serve all three consecutively when travel time between schools fits in
the gaps between windows.
"""

from isd_solver.domain import Crew, Driver, Job, Location, TimeWindow, Vehicle
from isd_solver.scheduler import InfeasibleResult, SchedulingResult
from isd_solver.scheduler import solve_multi_school_schedule as _solve_multi_school_schedule


def solve_multi_school_schedule(jobs, crews, deadhead_estimator):
    """Test-local wrapper: these are toy problems, so a single search
    worker and a short time limit avoid CP-SAT's parallel-search
    thread-pool startup overhead dominating the test suite's runtime."""
    return _solve_multi_school_schedule(
        jobs, crews, deadhead_estimator, time_limit_seconds=2.0, num_search_workers=1
    )


def _fixed_deadhead(minutes: int):
    """A deterministic deadhead estimator for tests, independent of geography."""

    def estimate(a: Location, b: Location) -> int:
        return 0 if a == b else minutes

    return estimate


def _crew(crew_id: str, earliest: int = 0, latest: int = 1439) -> Crew:
    return Crew(
        id=crew_id,
        driver=Driver(id=f"driver-{crew_id}", license_qualifications=frozenset({"CDL_B"})),
        vehicle=Vehicle(id=f"vehicle-{crew_id}"),
        available_window=TimeWindow(earliest=earliest, latest=latest),
    )


def _spec_section5_jobs() -> list[Job]:
    pre_k = Job(
        id="pre-k-run",
        school_id="pre-k-school",
        window=TimeWindow(earliest=360, latest=410),  # 6:00-6:50
        duration_minutes=40,
        buffer_minutes=10,
        location=Location(lat=29.70, lon=-95.40),
    )
    high_school = Job(
        id="hs-run",
        school_id="hs-school",
        window=TimeWindow(earliest=420, latest=470),  # 7:00-7:50
        duration_minutes=40,
        buffer_minutes=10,
        location=Location(lat=29.71, lon=-95.41),
    )
    middle_school = Job(
        id="ms-run",
        school_id="ms-school",
        window=TimeWindow(earliest=480, latest=540),  # 8:00-9:00
        duration_minutes=45,
        buffer_minutes=15,
        location=Location(lat=29.72, lon=-95.42),
    )
    return [pre_k, high_school, middle_school]


def test_single_crew_can_serve_all_three_bell_windows_when_deadhead_fits():
    jobs = _spec_section5_jobs()
    # 5 minutes deadhead fits inside both 10-minute gaps (410->420, 470->480).
    result = solve_multi_school_schedule(jobs, [_crew("C1")], _fixed_deadhead(5))

    assert isinstance(result, SchedulingResult)
    assert result.crews_used == 1
    crew_ids = {a.crew_id for a in result.assignments}
    assert crew_ids == {"C1"}

    by_job = {a.job_id: a for a in result.assignments}
    assert by_job["pre-k-run"].end_minute <= by_job["hs-run"].start_minute
    assert by_job["hs-run"].end_minute <= by_job["ms-run"].start_minute
    # Buffer to next job accounts for the 5-minute deadhead.
    assert by_job["pre-k-run"].explanation.buffer_minutes_to_next_job == 5
    assert by_job["ms-run"].explanation.next_job_id is None


def test_single_crew_infeasible_when_deadhead_exceeds_gap():
    jobs = _spec_section5_jobs()
    # 15 minutes deadhead does not fit inside the 10-minute gap between windows.
    result = solve_multi_school_schedule(jobs, [_crew("C1")], _fixed_deadhead(15))

    assert isinstance(result, InfeasibleResult)
    assert "hard constraint" in result.reason.lower() or "solver status" in result.reason.lower()


def test_two_crews_recover_feasibility_when_one_crew_cannot_chain_all_three():
    jobs = _spec_section5_jobs()
    result = solve_multi_school_schedule(
        jobs, [_crew("C1"), _crew("C2")], _fixed_deadhead(15)
    )

    assert isinstance(result, SchedulingResult)
    assert result.crews_used == 2
    assert {a.job_id for a in result.assignments} == {"pre-k-run", "hs-run", "ms-run"}


def test_unqualified_crew_is_never_assigned_a_job_requiring_a_qualification():
    plain_vehicle_crew = _crew("C1")
    lift_job = Job(
        id="lift-run",
        school_id="sped-school",
        window=TimeWindow(earliest=360, latest=420),
        duration_minutes=45,
        buffer_minutes=10,
        location=Location(lat=29.70, lon=-95.40),
        required_vehicle_qualifications=frozenset({"lift"}),
    )
    result = solve_multi_school_schedule([lift_job], [plain_vehicle_crew], _fixed_deadhead(0))

    assert isinstance(result, InfeasibleResult)
    assert "qualified" in result.reason.lower()


def test_qualified_crew_is_assigned_when_available():
    lift_vehicle = Vehicle(id="V-lift", qualifications=frozenset({"lift"}))
    crew = Crew(
        id="C-lift",
        driver=Driver(id="D-lift", license_qualifications=frozenset({"CDL_B"})),
        vehicle=lift_vehicle,
        available_window=TimeWindow(earliest=0, latest=1439),
    )
    lift_job = Job(
        id="lift-run",
        school_id="sped-school",
        window=TimeWindow(earliest=360, latest=420),
        duration_minutes=45,
        buffer_minutes=10,
        location=Location(lat=29.70, lon=-95.40),
        required_vehicle_qualifications=frozenset({"lift"}),
    )
    result = solve_multi_school_schedule([lift_job], [crew], _fixed_deadhead(0))

    assert isinstance(result, SchedulingResult)
    assert result.assignments[0].crew_id == "C-lift"


def test_no_crews_supplied_is_infeasible_not_a_crash():
    jobs = _spec_section5_jobs()
    result = solve_multi_school_schedule(jobs, [], _fixed_deadhead(5))
    assert isinstance(result, InfeasibleResult)


def test_no_jobs_returns_empty_feasible_result():
    result = solve_multi_school_schedule([], [_crew("C1")], _fixed_deadhead(5))
    assert isinstance(result, SchedulingResult)
    assert result.assignments == ()
    assert result.crews_used == 0


def test_capacity_insufficient_is_infeasible_with_clear_reason():
    small_vehicle = Vehicle(id="V-small", nominal_capacity=20, effective_capacity=18)
    crew = Crew(
        id="C-small",
        driver=Driver(id="D-small", license_qualifications=frozenset({"CDL_B"})),
        vehicle=small_vehicle,
        available_window=TimeWindow(earliest=0, latest=1439),
    )
    big_job = Job(
        id="big-run",
        school_id="es-school",
        window=TimeWindow(earliest=360, latest=420),
        duration_minutes=45,
        buffer_minutes=10,
        location=Location(lat=29.70, lon=-95.40),
        passenger_count=25,
    )
    result = solve_multi_school_schedule([big_job], [crew], _fixed_deadhead(0))

    assert isinstance(result, InfeasibleResult)
    assert "capacity" in result.reason.lower()
    assert "25" in result.reason


def test_capacity_sufficient_is_assigned():
    vehicle = Vehicle(id="V-big", nominal_capacity=48, effective_capacity=42)
    crew = Crew(
        id="C-big",
        driver=Driver(id="D-big", license_qualifications=frozenset({"CDL_B"})),
        vehicle=vehicle,
        available_window=TimeWindow(earliest=0, latest=1439),
    )
    job = Job(
        id="run",
        school_id="es-school",
        window=TimeWindow(earliest=360, latest=420),
        duration_minutes=45,
        buffer_minutes=10,
        location=Location(lat=29.70, lon=-95.40),
        passenger_count=40,
    )
    result = solve_multi_school_schedule([job], [crew], _fixed_deadhead(0))

    assert isinstance(result, SchedulingResult)
    assert "40 expected passengers" in result.assignments[0].explanation.text()


def test_unknown_vehicle_capacity_fails_closed_when_job_declares_riders():
    unknown_capacity_vehicle = Vehicle(id="V-unknown")  # no capacity fields set
    crew = Crew(
        id="C-unknown",
        driver=Driver(id="D-unknown", license_qualifications=frozenset({"CDL_B"})),
        vehicle=unknown_capacity_vehicle,
        available_window=TimeWindow(earliest=0, latest=1439),
    )
    job = Job(
        id="run",
        school_id="es-school",
        window=TimeWindow(earliest=360, latest=420),
        duration_minutes=45,
        buffer_minutes=10,
        location=Location(lat=29.70, lon=-95.40),
        passenger_count=10,
    )
    result = solve_multi_school_schedule([job], [crew], _fixed_deadhead(0))

    assert isinstance(result, InfeasibleResult)


def test_job_with_zero_passenger_count_ignores_capacity_entirely():
    # A job that doesn't model ridership should still schedule against
    # a vehicle with unknown or zero-relevant capacity.
    unknown_capacity_vehicle = Vehicle(id="V-unknown")
    crew = Crew(
        id="C-unknown",
        driver=Driver(id="D-unknown", license_qualifications=frozenset({"CDL_B"})),
        vehicle=unknown_capacity_vehicle,
        available_window=TimeWindow(earliest=0, latest=1439),
    )
    job = Job(
        id="run",
        school_id="es-school",
        window=TimeWindow(earliest=360, latest=420),
        duration_minutes=45,
        buffer_minutes=10,
        location=Location(lat=29.70, lon=-95.40),
    )  # passenger_count defaults to 0
    result = solve_multi_school_schedule([job], [crew], _fixed_deadhead(0))
    assert isinstance(result, SchedulingResult)


def test_explanation_text_is_human_readable_and_cites_checked_constraints():
    jobs = _spec_section5_jobs()
    result = solve_multi_school_schedule(jobs, [_crew("C1")], _fixed_deadhead(5))
    assert isinstance(result, SchedulingResult)
    text = result.assignments[0].explanation.text()
    assert "C1" in text
    assert "qualifications" in text
