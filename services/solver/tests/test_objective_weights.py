"""Configurable soft-constraint objectives (spec section 2.2): weights
over crews used, deadhead travel, and arrival buffer."""

import pytest

from isd_solver.domain import Crew, Driver, Job, Location, TimeWindow, Vehicle
from isd_solver.scheduler import ObjectiveWeights, SchedulingResult, solve_multi_school_schedule

DEADHEAD = 20


def _estimator(a: Location, b: Location, vehicle: Vehicle) -> int:
    return 0 if a == b else DEADHEAD


def _crew(crew_id: str) -> Crew:
    return Crew(
        id=crew_id,
        driver=Driver(id=f"driver-{crew_id}", license_qualifications=frozenset({"CDL_B"})),
        vehicle=Vehicle(id=f"vehicle-{crew_id}"),
        available_window=TimeWindow(earliest=0, latest=1439),
    )


def _job(job_id: str, earliest: int, latest: int, lat: float) -> Job:
    return Job(
        id=job_id,
        school_id=f"school-{job_id}",
        window=TimeWindow(earliest=earliest, latest=latest),
        duration_minutes=40,
        buffer_minutes=10,
        location=Location(lat=lat, lon=-95.4),
    )


def _solve(jobs, crews, weights=None) -> SchedulingResult:
    result = solve_multi_school_schedule(
        jobs, crews, _estimator, time_limit_seconds=5.0, num_search_workers=1, weights=weights
    )
    assert isinstance(result, SchedulingResult), result
    return result


def _chainable_pair() -> list[Job]:
    # Occupies 50 min each. A ends by 410; B must start >= 410 + 20 = 430.
    return [_job("a", 360, 410, 29.70), _job("b", 440, 500, 29.71)]


def test_default_weights_match_the_original_minimize_crews_behavior():
    jobs = _chainable_pair()
    crews = [_crew("c1"), _crew("c2")]
    assert _solve(jobs, crews).crews_used == 1
    assert _solve(jobs, crews, ObjectiveWeights()).crews_used == 1


def test_heavy_deadhead_weight_prefers_more_crews_over_deadhead_travel():
    jobs = _chainable_pair()
    crews = [_crew("c1"), _crew("c2")]
    # 1 crew costs 10 + 20 deadhead = 30; 2 crews cost 20 + 0 = 20.
    result = _solve(jobs, crews, ObjectiveWeights(crews_used=10, deadhead_minutes=1))
    assert result.crews_used == 2
    assert result.total_deadhead_minutes == 0


def test_heavy_crew_weight_still_chains_onto_one_crew_despite_deadhead():
    jobs = _chainable_pair()
    crews = [_crew("c1"), _crew("c2")]
    # 1 crew costs 100 + 20 = 120; 2 crews cost 200.
    result = _solve(jobs, crews, ObjectiveWeights(crews_used=100, deadhead_minutes=1))
    assert result.crews_used == 1
    assert result.total_deadhead_minutes == DEADHEAD


def test_deadhead_weight_never_breaks_a_hard_constraint():
    """Even an overwhelming deadhead weight can't buy an overlap: with a
    single crew the chain is the only option, and it stays feasible."""
    jobs = _chainable_pair()
    result = _solve(jobs, [_crew("only")], ObjectiveWeights(crews_used=1, deadhead_minutes=1000))
    assert result.crews_used == 1
    starts = {a.job_id: a.start_minute for a in result.assignments}
    ends = {a.job_id: a.end_minute for a in result.assignments}
    assert ends["a"] + DEADHEAD <= starts["b"]


def test_arrival_buffer_weight_finishes_jobs_as_early_as_the_window_allows():
    job = _job("solo", 360, 500, 29.70)  # occupies 50 min inside a 140 min window
    result = _solve([job], [_crew("c1")], ObjectiveWeights(crews_used=1, arrival_buffer=1))
    (assignment,) = result.assignments
    assert (assignment.start_minute, assignment.end_minute) == (360, 410)
    assert result.total_arrival_buffer_minutes == 500 - 410


def test_reported_totals_are_exact_regardless_of_weights():
    result = _solve(_chainable_pair(), [_crew("c1")])
    assert result.total_deadhead_minutes == DEADHEAD
    ends = {a.job_id: a.end_minute for a in result.assignments}
    assert result.total_arrival_buffer_minutes == (410 - ends["a"]) + (500 - ends["b"])


def test_deadhead_weight_ignored_cleanly_when_no_jobs_share_a_crew():
    result = _solve([_job("solo", 360, 500, 29.70)], [_crew("c1")], ObjectiveWeights(1, 5, 0))
    assert result.crews_used == 1
    assert result.total_deadhead_minutes == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"crews_used": -1},
        {"deadhead_minutes": -5},
        {"arrival_buffer": -1},
        {"crews_used": 0, "deadhead_minutes": 0, "arrival_buffer": 0},
        {"crews_used": 1.5},
        {"crews_used": True},
    ],
)
def test_invalid_weights_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ObjectiveWeights(**kwargs)


def test_zero_crew_weight_is_allowed_when_another_objective_is_positive():
    weights = ObjectiveWeights(crews_used=0, deadhead_minutes=1)
    assert weights.deadhead_minutes == 1


def _three_in_a_row() -> list[Job]:
    # Each occupies 50 min, 20 min apart by road: a, then b, then c.
    return [_job("a", 360, 410, 29.70), _job("b", 430, 480, 29.71), _job("c", 500, 550, 29.72)]


def test_empty_driving_is_counted_along_the_chain_not_between_every_pair():
    """One crew drives a, b, c: 40 minutes empty (a to b, b to c), not 60
    (a to c as well). So one crew (35 + 40 = 75) beats two (70 + 20)."""
    result = _solve(
        _three_in_a_row(),
        [_crew("c1"), _crew("c2"), _crew("c3")],
        ObjectiveWeights(crews_used=35, deadhead_minutes=1),
    )
    assert result.crews_used == 1
    assert result.total_deadhead_minutes == 40


def _crew_parked_at(crew_id: str, lat: float) -> Crew:
    crew = _crew(crew_id)
    return Crew(
        id=crew.id,
        driver=crew.driver,
        vehicle=Vehicle(id=f"vehicle-{crew_id}", yard=Location(lat=lat, lon=-95.4)),
        available_window=crew.available_window,
    )


def test_the_bus_parked_nearest_takes_the_run():
    job = _job("a", 360, 410, 29.70)
    far, near = _crew_parked_at("far", 29.90), _crew_parked_at("near", 29.70)
    result = _solve([job], [far, near], ObjectiveWeights(crews_used=1, deadhead_minutes=1))
    assert result.assignments[0].crew_id == "near"
    assert result.total_yard_minutes == 0

    only_far = _solve([job], [far], ObjectiveWeights(crews_used=1, deadhead_minutes=1))
    # Out from the yard and back again.
    assert only_far.total_yard_minutes == 2 * DEADHEAD


def test_a_chain_starts_and_ends_at_the_yard():
    crew = _crew_parked_at("c1", 29.70)  # parked at a
    result = _solve(_three_in_a_row(), [crew], ObjectiveWeights(crews_used=1, deadhead_minutes=1))
    assert [a.job_id for a in sorted(result.assignments, key=lambda a: a.start_minute)] == [
        "a",
        "b",
        "c",
    ]
    assert (result.total_deadhead_minutes, result.total_yard_minutes) == (40, 20)
