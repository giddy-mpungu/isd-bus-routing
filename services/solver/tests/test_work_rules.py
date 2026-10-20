"""District driver work-hour rules (spec section 2.1): a daily duty limit
and a required break, both off unless the district sets them."""

import pytest

from isd_solver.domain import Crew, Driver, Job, Location, TimeWindow, Vehicle
from isd_solver.scheduler import (
    InfeasibleResult,
    SchedulingResult,
    WorkRules,
    duty_limit,
    solve_multi_school_schedule,
)

SCHOOL_A = Location(lat=29.70, lon=-95.40)
SCHOOL_B = Location(lat=29.75, lon=-95.45)


def _deadhead(minutes: int):
    def estimate(a: Location, b: Location, vehicle: Vehicle) -> int:
        return 0 if a == b else minutes

    return estimate


def _crew(crew_id: str, max_continuous_minutes: int | None = None) -> Crew:
    return Crew(
        id=crew_id,
        driver=Driver(id=f"driver-{crew_id}", max_continuous_minutes=max_continuous_minutes),
        vehicle=Vehicle(id=f"vehicle-{crew_id}"),
        available_window=TimeWindow(earliest=0, latest=1439),
    )


def _job(job_id: str, earliest: int, latest: int, minutes: int, at: Location = SCHOOL_A) -> Job:
    return Job(
        id=job_id,
        school_id=f"school-{job_id}",
        window=TimeWindow(earliest=earliest, latest=latest),
        duration_minutes=minutes,
        buffer_minutes=0,
        location=at,
    )


def _solve(jobs, crews, rules=None, deadhead=0):
    return solve_multi_school_schedule(
        jobs,
        crews,
        _deadhead(deadhead),
        time_limit_seconds=5.0,
        num_search_workers=1,
        work_rules=rules,
    )


def _by_job(result):
    assert isinstance(result, SchedulingResult), result
    return {a.job_id: a for a in result.assignments}


def test_rules_off_change_nothing():
    jobs = [_job("am", 360, 420, 60), _job("pm", 840, 900, 60)]
    result = _solve(jobs, [_crew("1"), _crew("2")])
    assert result.crews_used == 1


def test_a_daily_duty_limit_splits_a_long_day_between_drivers():
    # 06:00-07:00 and 14:00-15:00: nine hours from first start to last end.
    jobs = [_job("am", 360, 420, 60), _job("pm", 840, 900, 60)]
    rules = WorkRules(max_duty_minutes=8 * 60)
    result = _solve(jobs, [_crew("1"), _crew("2")], rules)
    assert result.crews_used == 2
    assert isinstance(_solve(jobs, [_crew("1")], rules), InfeasibleResult)


def test_the_tighter_of_the_drivers_and_the_districts_limits_applies():
    rules = WorkRules(max_duty_minutes=600)
    assert duty_limit(_crew("1", max_continuous_minutes=480), rules) == 480
    assert duty_limit(_crew("1", max_continuous_minutes=720), rules) == 600
    assert duty_limit(_crew("1"), rules) == 600
    assert duty_limit(_crew("1"), WorkRules()) is None


def test_a_break_is_made_room_for():
    # 90 minutes of work before a 30-minute break: the second run waits.
    jobs = [_job("first", 360, 420, 60), _job("second", 420, 600, 60)]
    rules = WorkRules(break_after_minutes=90, break_minutes=30)
    by_job = _by_job(_solve(jobs, [_crew("1")], rules))
    assert by_job["second"].start_minute >= 420 + 30


def test_without_room_for_a_break_the_work_goes_to_another_driver():
    # Back to back, no slack: 06:00-07:00, 07:00-08:00, 08:00-09:00.
    jobs = [_job("a", 360, 420, 60), _job("b", 420, 480, 60), _job("c", 480, 540, 60)]
    rules = WorkRules(break_after_minutes=120, break_minutes=30)
    result = _solve(jobs, [_crew("1"), _crew("2")], rules)
    assert result.crews_used == 2
    assert isinstance(_solve(jobs, [_crew("1")], rules), InfeasibleResult)


def test_a_chain_of_short_gaps_is_still_one_stretch_of_work():
    # Four 40-minute runs with 10-minute gaps: no pair is far apart, but
    # together they're 190 minutes without a 30-minute break.
    jobs = [
        _job("a", 360, 400, 40),
        _job("b", 410, 450, 40),
        _job("c", 460, 500, 40),
        _job("d", 510, 550, 40),
    ]
    rules = WorkRules(break_after_minutes=150, break_minutes=30)
    assert isinstance(_solve(jobs, [_crew("1")], rules), InfeasibleResult)
    assert isinstance(_solve(jobs, [_crew("1")]), SchedulingResult)


def test_driving_between_schools_isnt_a_break():
    jobs = [
        _job("first", 360, 420, 60, at=SCHOOL_A),
        _job("second", 420, 600, 60, at=SCHOOL_B),
    ]
    rules = WorkRules(break_after_minutes=90, break_minutes=30)
    by_job = _by_job(_solve(jobs, [_crew("1")], rules, deadhead=20))
    assert by_job["second"].start_minute >= 420 + 20 + 30


def test_a_run_longer_than_the_work_allowed_before_a_break_says_why():
    rules = WorkRules(break_after_minutes=60, break_minutes=15)
    result = _solve([_job("long", 360, 480, 90)], [_crew("1")], rules)
    assert isinstance(result, InfeasibleResult)
    assert "60 minutes of work allowed before a break" in result.reason


def test_the_explanation_names_the_rules_it_kept():
    rules = WorkRules(max_duty_minutes=600, break_after_minutes=240, break_minutes=30)
    [assignment] = _by_job(_solve([_job("am", 360, 420, 60)], [_crew("1")], rules)).values()
    text = " ".join(assignment.explanation.hard_constraints_checked)
    assert "continuous-duty limit (600 min)" in text
    assert "30-minute break at least every 240 minutes" in text


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_duty_minutes": 0},
        {"break_after_minutes": 120},
        {"break_minutes": 30},
        {"break_after_minutes": -1, "break_minutes": 30},
    ],
)
def test_rules_are_validated(kwargs):
    with pytest.raises(ValueError):
        WorkRules(**kwargs)


def test_wheelchair_riders_need_a_bus_with_enough_positions():
    job = Job(
        id="run",
        school_id="s",
        window=TimeWindow(earliest=360, latest=420),
        duration_minutes=60,
        buffer_minutes=0,
        location=SCHOOL_A,
        passenger_count=5,
        wheelchair_riders=2,
    )

    def crew(crew_id, positions):
        return Crew(
            id=crew_id,
            driver=Driver(id=f"d{crew_id}"),
            vehicle=Vehicle(id=f"v{crew_id}", nominal_capacity=20, wheelchair_positions=positions),
            available_window=TimeWindow(earliest=0, latest=1439),
        )

    assert not crew("1", None).has_capacity_for(job)  # not recorded: fails closed
    assert not crew("1", 1).has_capacity_for(job)
    assert crew("1", 2).has_capacity_for(job)
    [assignment] = _by_job(_solve([job], [crew("1", 1), crew("2", 4)])).values()
    assert assignment.crew_id == "2"
    refused = _solve([job], [crew("1", 1)])
    assert isinstance(refused, InfeasibleResult)
    assert "enough wheelchair positions for 2" in refused.reason
