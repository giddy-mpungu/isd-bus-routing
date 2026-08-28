"""Run the spec section 5 worked example and print what actually happened.

pytest tells you whether the solver's behavior matches expectations; it
deliberately doesn't print the schedule it found. This script is for
seeing the real output: the assignment, timing, and the explanation
text spec section 21 requires.

Usage:
    python examples/run_worked_example.py
"""

from __future__ import annotations

import logging

from isd_solver import (
    Crew,
    Driver,
    InfeasibleResult,
    Job,
    Location,
    SchedulingResult,
    TimeWindow,
    Vehicle,
    solve_multi_school_schedule,
    straight_line_deadhead_estimator,
)


def _minute_to_clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    jobs = [
        Job(
            id="pre-k-run",
            school_id="pre-k-school",
            window=TimeWindow(earliest=360, latest=410),  # 6:00-6:50
            duration_minutes=40,
            buffer_minutes=10,
            location=Location(lat=29.70, lon=-95.40),
            passenger_count=12,
        ),
        Job(
            id="hs-run",
            school_id="hs-school",
            window=TimeWindow(earliest=420, latest=470),  # 7:00-7:50
            duration_minutes=40,
            buffer_minutes=10,
            location=Location(lat=29.71, lon=-95.41),
            passenger_count=35,
        ),
        Job(
            id="ms-run",
            school_id="ms-school",
            window=TimeWindow(earliest=480, latest=540),  # 8:00-9:00
            duration_minutes=45,
            buffer_minutes=15,
            location=Location(lat=29.72, lon=-95.42),
            passenger_count=28,
        ),
    ]

    crew = Crew(
        id="C1",
        driver=Driver(id="D1", license_qualifications=frozenset({"CDL_B"})),
        vehicle=Vehicle(id="V1", nominal_capacity=48, effective_capacity=44),
        available_window=TimeWindow(earliest=0, latest=1439),
    )

    print("\n--- Solving spec section 5 worked example (Pre-K -> HS -> MS) ---\n")
    result = solve_multi_school_schedule(
        jobs, [crew], straight_line_deadhead_estimator(average_speed_kmh=25.0)
    )

    if isinstance(result, InfeasibleResult):
        print(f"INFEASIBLE: {result.reason}")
        return

    assert isinstance(result, SchedulingResult)
    print(f"Feasible schedule found using {result.crews_used} crew(s):\n")
    for assignment in sorted(result.assignments, key=lambda a: a.start_minute):
        print(
            f"  {assignment.job_id}: crew {assignment.crew_id}, "
            f"{_minute_to_clock(assignment.start_minute)}-{_minute_to_clock(assignment.end_minute)}"
        )
        print(f"    {assignment.explanation.text()}\n")


if __name__ == "__main__":
    main()
