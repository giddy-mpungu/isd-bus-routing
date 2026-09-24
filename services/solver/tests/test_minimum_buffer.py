"""Minimum operational buffer between consecutive jobs (spec section 16:
"a mathematically feasible schedule should be rejected or flagged if it
lacks sufficient operational buffer")."""

import pytest

from isd_solver.domain import Crew, Driver, Job, Location, TimeWindow, Vehicle
from isd_solver.scheduler import InfeasibleResult, SchedulingResult, solve_multi_school_schedule

DEADHEAD = 20


def _estimator(a: Location, b: Location, vehicle: Vehicle) -> int:
    return 0 if a == b else DEADHEAD


def _crew(crew_id: str) -> Crew:
    return Crew(
        id=crew_id,
        driver=Driver(id=f"driver-{crew_id}"),
        vehicle=Vehicle(id=f"vehicle-{crew_id}"),
        available_window=TimeWindow(earliest=0, latest=1439),
    )


def _pair() -> list[Job]:
    # Each job occupies 50 min. A must end by 410; B may start 440-450.
    # Chained on one crew, the spare time after 20 min of deadhead is at
    # most 450 - 410 - 20 = 20 minutes.
    def job(job_id: str, earliest: int, latest: int, lat: float) -> Job:
        return Job(
            id=job_id,
            school_id=f"school-{job_id}",
            window=TimeWindow(earliest=earliest, latest=latest),
            duration_minutes=40,
            buffer_minutes=10,
            location=Location(lat=lat, lon=-95.4),
        )

    return [job("a", 360, 410, 29.70), job("b", 440, 500, 29.71)]


def _solve(jobs, crews, minimum):
    return solve_multi_school_schedule(
        jobs,
        crews,
        _estimator,
        time_limit_seconds=5.0,
        num_search_workers=1,
        minimum_buffer_minutes=minimum,
    )


def test_no_minimum_keeps_the_original_behaviour():
    result = _solve(_pair(), [_crew("c1"), _crew("c2")], 0)
    assert isinstance(result, SchedulingResult)
    assert result.crews_used == 1


def test_a_minimum_the_chain_can_meet_still_chains_with_that_much_buffer():
    result = _solve(_pair(), [_crew("c1"), _crew("c2")], 20)
    assert isinstance(result, SchedulingResult)
    assert result.crews_used == 1
    first = next(a for a in result.assignments if a.job_id == "a")
    assert first.explanation.buffer_minutes_to_next_job is not None
    assert first.explanation.buffer_minutes_to_next_job >= 20
    assert "at least 20 minutes of operational buffer" in first.explanation.text()


def test_a_minimum_the_chain_cannot_meet_splits_the_jobs_across_crews():
    result = _solve(_pair(), [_crew("c1"), _crew("c2")], 21)
    assert isinstance(result, SchedulingResult)
    assert result.crews_used == 2


def test_a_minimum_no_plan_can_meet_is_rejected_rather_than_scheduled_tightly():
    result = _solve(_pair(), [_crew("c1")], 21)
    assert isinstance(result, InfeasibleResult)


def test_negative_minimum_is_refused():
    with pytest.raises(ValueError, match="minimum_buffer_minutes"):
        _solve(_pair(), [_crew("c1")], -1)
