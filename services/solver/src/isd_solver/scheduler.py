"""Multi-school crew scheduling solver (spec section 5, Phase 1).

Given a set of Jobs (one per school bell-window run) and a set of
Crews (driver+vehicle pairs), determine whether crews can be chained
across multiple schools' bell windows without violating any hard
constraint (spec section 2.1), and if so, the assignment that uses the
fewest crews (spec section 2.2, objective 1).

Hard constraints implemented here (each traceable to a spec section,
per ADR 0002):
  - A job is only assignable to a crew qualified for it (spec section 1,
    15: driver/vehicle qualification).
  - A crew cannot be assigned two overlapping jobs, and when a crew
    serves two jobs at different schools, there must be enough time
    between them for deadhead travel (spec section 5: "travel between
    assignments", spec section 2.1: "assigns one driver or vehicle to
    overlapping assignments").
  - A job must start and finish inside its own required arrival window
    (spec section 2.1) and inside its assigned crew's availability
    window.
  - A crew's driver never exceeds their configured max_continuous_minutes
    (spec section 2.1: "driver scheduling or work-hour rules"; section
    16: operational time). Modeled as one continuous duty span from a
    crew's first assigned job start to its last assigned job end — a
    Phase 1 approximation that doesn't yet recognize a gap between jobs
    as a qualifying break (see docs/domain-model.md). This is a
    district-configured value; this codebase makes no claim about what
    any specific driver-hour law requires.
  - A job is never scheduled into a crew's busy_intervals (spec section
    21: a locked assignment protects that specific commitment, not the
    crew's whole day — routers/schedule.py populates this from a
    crew's other locked assignments on a re-solve). No deadhead buffer
    is enforced around a busy interval — see Crew's docstring.

Soft objectives implemented here (spec section 2.2), combined as a
weighted sum with administrator-configurable weights (ObjectiveWeights):
  - crews_used: minimize the number of distinct crews (objectives 1-2,
    buses/drivers — a crew is one driver+one vehicle, so they coincide).
  - deadhead_minutes: minimize deadhead travel between jobs sharing a
    crew (objective 3's mileage, measured in travel minutes since that
    is what the DeadheadEstimator returns). Applied to every pair of
    jobs on a shared crew, not only adjacent ones, so for a crew with
    3+ jobs it over-counts relative to the true chain — see
    ObjectiveWeights. The reported total_deadhead_minutes is exact.
  - arrival_buffer: finish jobs earlier, leaving more slack before each
    school's required window end (objective 10, operational buffers).
The rest (stops, ride time, walking, turns) need data this system does
not model yet — see docs/domain-model.md.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

from isd_solver.domain import Crew, DeadheadEstimator, Job

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObjectiveWeights:
    """Relative weights for the soft objectives (spec section 2.2:
    "administrators should be able to configure the relative weights").
    Non-negative integers (CP-SAT needs an integer objective); a larger
    weight makes that objective matter more. Hard constraints are never
    traded off against these — they only rank feasible schedules.

    The defaults reproduce the original behavior exactly (minimize crews
    used, nothing else). Units differ — crews_used counts crews while
    the other two count minutes — so to let mileage or buffers matter
    against a whole crew, give crews_used a proportionally larger weight
    (e.g. 100 vs 1).

    deadhead_minutes is a pairwise measure: every two jobs sharing a
    crew contribute their deadhead between them in the order actually
    driven, whether or not they are adjacent. It is exact for crews with
    up to two jobs and over-counts non-adjacent pairs beyond that;
    SchedulingResult.total_deadhead_minutes is always the exact chain
    total, computed after solving.
    """

    crews_used: int = 1
    deadhead_minutes: int = 0
    arrival_buffer: int = 0

    def __post_init__(self) -> None:
        for name in ("crews_used", "deadhead_minutes", "arrival_buffer"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} weight must be a non-negative integer, got {value!r}")
        if self.crews_used == 0 and self.deadhead_minutes == 0 and self.arrival_buffer == 0:
            raise ValueError("at least one objective weight must be greater than zero")


@dataclass(frozen=True)
class Explanation:
    """Structured explanation for one assignment (spec section 21).

    text() renders this into the human-readable form shown in the
    spec's example. Kept structured (not just a string) per ADR 0004
    so the explanation can't claim anything the solver didn't actually
    check.
    """

    job_id: str
    crew_id: str
    hard_constraints_checked: tuple[str, ...]
    buffer_minutes_to_next_job: int | None
    next_job_id: str | None

    def text(self) -> str:
        parts = [
            f"Crew {self.crew_id} was assigned job {self.job_id} because "
            + "; ".join(self.hard_constraints_checked)
            + "."
        ]
        if self.next_job_id is not None and self.buffer_minutes_to_next_job is not None:
            parts.append(
                f"{self.buffer_minutes_to_next_job} minutes of operational buffer "
                f"remain before its next job ({self.next_job_id})."
            )
        return " ".join(parts)


@dataclass(frozen=True)
class Assignment:
    job_id: str
    crew_id: str
    start_minute: int
    end_minute: int
    explanation: Explanation


@dataclass(frozen=True)
class SchedulingResult:
    assignments: tuple[Assignment, ...]
    crews_used: int
    # Exact totals of the realized schedule (independent of the weights):
    # deadhead travel between consecutive jobs on the same crew, and the
    # summed slack between each job's end and its window's latest bound.
    total_deadhead_minutes: int = 0
    total_arrival_buffer_minutes: int = 0


@dataclass(frozen=True)
class InfeasibleResult:
    reason: str


def solve_multi_school_schedule(
    jobs: Sequence[Job],
    crews: Sequence[Crew],
    deadhead_estimator: DeadheadEstimator,
    time_limit_seconds: float = 10.0,
    num_search_workers: int = 8,
    weights: ObjectiveWeights | None = None,
    minimum_buffer_minutes: int = 0,
) -> SchedulingResult | InfeasibleResult:
    """Solve the multi-school crew scheduling problem (spec section 5).

    minimum_buffer_minutes (spec section 16) is a hard floor on the spare
    time between consecutive jobs on the same crew, after deadhead travel:
    the same quantity each Explanation reports as buffer_minutes_to_next_job.
    0 (the default) means no floor beyond the jobs' own buffer_minutes.

    num_search_workers controls CP-SAT's internal parallel search
    threads. 8 is a reasonable default for real problem sizes; for
    small problems (tests, toy examples) a lower value (e.g. 1-2) avoids
    thread-pool startup overhead dominating the runtime.
    """
    weights = weights or ObjectiveWeights()
    if minimum_buffer_minutes < 0:
        raise ValueError(f"minimum_buffer_minutes must be >= 0, got {minimum_buffer_minutes}")
    logger.info("Solving multi-school schedule: %d job(s), %d crew(s)", len(jobs), len(crews))
    if not jobs:
        logger.info("No jobs supplied — nothing to schedule.")
        return SchedulingResult(assignments=(), crews_used=0)
    if not crews:
        logger.warning("No crews supplied — cannot schedule any job.")
        return InfeasibleResult("No crews supplied — cannot schedule any job.")

    # --- Precompute which crews can even legally take each job ---
    candidate_crews: dict[str, list[Crew]] = {}
    for job in jobs:
        window_ok = [
            crew
            for crew in crews
            if crew.available_window.earliest <= job.window.earliest
            and crew.available_window.latest >= job.window.latest
        ]
        qualified = [crew for crew in window_ok if crew.is_qualified_for(job)]
        capacity_ok = [crew for crew in qualified if crew.has_capacity_for(job)]
        # A job that, on its own, already exceeds a crew's driver's
        # continuous-duty limit can never be assigned to that crew —
        # no chaining is even involved yet.
        duty_ok = [
            crew
            for crew in capacity_ok
            if crew.driver.max_continuous_minutes is None
            or job.total_occupied_minutes <= crew.driver.max_continuous_minutes
        ]

        if not duty_ok:
            reasons: list[str] = []
            if not window_ok:
                reasons.append(
                    "no crew's availability window covers this job's required "
                    f"window [{job.window.earliest}, {job.window.latest}]"
                )
            elif not qualified:
                unqualified_ids = [c.id for c in window_ok]
                reasons.append(
                    "no available crew is qualified for this job's requirements "
                    f"{sorted(job.required_vehicle_qualifications) or '(license only)'} "
                    f"(checked crews: {unqualified_ids})"
                )
            elif not capacity_ok:
                under_capacity_ids = [(c.id, c.vehicle.allowable_capacity()) for c in qualified]
                reasons.append(
                    f"no qualified/available crew has enough vehicle capacity for "
                    f"{job.passenger_count} expected passengers "
                    f"(checked crews and their allowable capacity: {under_capacity_ids})"
                )
            else:
                over_limit_ids = [(c.id, c.driver.max_continuous_minutes) for c in capacity_ok]
                reasons.append(
                    f"this job alone ({job.total_occupied_minutes} min) exceeds every "
                    "otherwise-eligible crew's driver's max_continuous_minutes limit "
                    f"(checked crews and their limits: {over_limit_ids})"
                )
            reason = f"Job {job.id}: " + "; ".join(reasons) + "."
            logger.warning(reason)
            return InfeasibleResult(reason)

        candidate_crews[job.id] = duty_ok
        logger.debug(
            "Job %s: %d candidate crew(s) after qualification/availability/capacity/duty filtering",
            job.id,
            len(duty_ok),
        )

    model = cp_model.CpModel()

    start_vars: dict[str, cp_model.IntVar] = {}
    end_vars: dict[str, cp_model.IntVar] = {}
    for job in jobs:
        latest_start = job.window.latest - job.total_occupied_minutes
        start = model.NewIntVar(job.window.earliest, latest_start, f"start_{job.id}")
        end = model.NewIntVar(
            job.window.earliest + job.total_occupied_minutes,
            job.window.latest,
            f"end_{job.id}",
        )
        model.Add(end == start + job.total_occupied_minutes)
        start_vars[job.id] = start
        end_vars[job.id] = end

    # x[job.id][crew.id] = 1 if that crew serves that job
    x: dict[str, dict[str, cp_model.IntVar]] = {}
    for job in jobs:
        x[job.id] = {}
        for crew in candidate_crews[job.id]:
            var = model.NewBoolVar(f"x_{job.id}_{crew.id}")
            x[job.id][crew.id] = var
            model.Add(start_vars[job.id] >= crew.available_window.earliest).OnlyEnforceIf(var)
            model.Add(end_vars[job.id] <= crew.available_window.latest).OnlyEnforceIf(var)
        # exactly one crew per job
        model.AddExactlyOne(list(x[job.id].values()))

    crew_by_id = {crew.id: crew for crew in crews}

    # Pairwise ordering when two jobs share a crew: whichever comes
    # first must finish, plus deadhead travel time, before the other
    # starts. Also, if that crew's driver has a continuous-duty limit,
    # the span from the earlier job's start to the later job's end must
    # not exceed it — applied to every pair (not just adjacent ones in
    # a chain), which is what makes it correctly bound the full span
    # for a crew working any number of jobs in a day, not just two.
    job_list = list(jobs)
    deadhead_cost_terms: list[cp_model.LinearExpr] = []
    for i in range(len(job_list)):
        for j in range(i + 1, len(job_list)):
            job_a, job_b = job_list[i], job_list[j]
            shared_crew_ids = {c.id for c in candidate_crews[job_a.id]} & {
                c.id for c in candidate_crews[job_b.id]
            }
            if not shared_crew_ids:
                continue
            order = model.NewBoolVar(f"order_{job_a.id}_before_{job_b.id}")
            for crew_id in shared_crew_ids:
                vehicle = crew_by_id[crew_id].vehicle
                deadhead_ab = deadhead_estimator(job_a.location, job_b.location, vehicle)
                deadhead_ba = deadhead_estimator(job_b.location, job_a.location, vehicle)
                both = [x[job_a.id][crew_id], x[job_b.id][crew_id]]
                gap = minimum_buffer_minutes
                model.Add(
                    end_vars[job_a.id] + deadhead_ab + gap <= start_vars[job_b.id]
                ).OnlyEnforceIf(both + [order])
                model.Add(
                    end_vars[job_b.id] + deadhead_ba + gap <= start_vars[job_a.id]
                ).OnlyEnforceIf(both + [order.Not()])
                if weights.deadhead_minutes > 0:
                    # Only ever forced true, never false: the objective
                    # is minimized and costs are non-negative, so an
                    # unforced cost variable settles at 0 on its own.
                    for cost, direction in ((deadhead_ab, order), (deadhead_ba, order.Not())):
                        if cost <= 0:
                            continue
                        paid = model.NewBoolVar(f"dh_{job_a.id}_{job_b.id}_{crew_id}_{cost}")
                        model.AddBoolOr(
                            [
                                x[job_a.id][crew_id].Not(),
                                x[job_b.id][crew_id].Not(),
                                direction.Not(),
                                paid,
                            ]
                        )
                        deadhead_cost_terms.append(cost * paid)
                max_continuous = crew_by_id[crew_id].driver.max_continuous_minutes
                if max_continuous is not None:
                    model.Add(
                        end_vars[job_b.id] - start_vars[job_a.id] <= max_continuous
                    ).OnlyEnforceIf(both + [order])
                    model.Add(
                        end_vars[job_a.id] - start_vars[job_b.id] <= max_continuous
                    ).OnlyEnforceIf(both + [order.Not()])

    # A crew with busy_intervals (spec section 21: locked assignments
    # elsewhere in its day) can't be given a job that overlaps one —
    # same disjunctive shape as the pairwise ordering above, but
    # against a fixed interval instead of another job's variables, so
    # no deadhead buffer is added (there's no location for whatever's
    # occupying that interval).
    for job in jobs:
        for crew in candidate_crews[job.id]:
            if not crew.busy_intervals:
                continue
            var = x[job.id][crew.id]
            for idx, busy in enumerate(crew.busy_intervals):
                before_busy = model.NewBoolVar(f"before_busy_{job.id}_{crew.id}_{idx}")
                model.Add(end_vars[job.id] <= busy.earliest).OnlyEnforceIf([var, before_busy])
                model.Add(start_vars[job.id] >= busy.latest).OnlyEnforceIf([var, before_busy.Not()])

    # crew_used[c] = 1 if crew c serves at least one job
    all_crew_ids = {crew.id for crew in crews}
    crew_used: dict[str, cp_model.IntVar] = {}
    for crew_id in all_crew_ids:
        assigned_literals = [x[job.id][crew_id] for job in jobs if crew_id in x[job.id]]
        used = model.NewBoolVar(f"used_{crew_id}")
        if assigned_literals:
            model.AddMaxEquality(used, assigned_literals)
        else:
            model.Add(used == 0)
        crew_used[crew_id] = used

    objective = weights.crews_used * sum(crew_used.values())
    if weights.deadhead_minutes > 0 and deadhead_cost_terms:
        objective += weights.deadhead_minutes * sum(deadhead_cost_terms)
    if weights.arrival_buffer > 0:
        # Maximizing slack (latest - end) is minimizing end; the constant
        # `latest` terms don't change which schedule wins.
        objective += weights.arrival_buffer * sum(end_vars[job.id] for job in jobs)
    model.Minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = num_search_workers
    status = solver.Solve(model)
    logger.info(
        "CP-SAT finished: status=%s, wall_time=%.3fs, branches=%d",
        solver.StatusName(status),
        solver.WallTime(),
        solver.NumBranches(),
    )

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        reason = (
            "No schedule satisfies all hard constraints for the given jobs and "
            "crews (solver status: "
            f"{solver.StatusName(status)}, {len(jobs)} job(s), {len(crews)} crew(s), "
            f"wall_time={solver.WallTime():.3f}s). This usually means more crews are "
            "needed, or a job's window is too tight given deadhead travel — each "
            "job individually has a qualified/available/capacity-sufficient crew "
            "(checked above), so this infeasibility comes from the pairwise "
            "sequencing constraints (spec section 2.1: overlapping assignments)."
        )
        logger.warning(reason)
        return InfeasibleResult(reason)

    # --- Build assignments + explanations from the solved model ---
    job_to_crew: dict[str, str] = {}
    for job in jobs:
        for crew_id, var in x[job.id].items():
            if solver.Value(var) == 1:
                job_to_crew[job.id] = crew_id
                break

    # Order each crew's jobs by start time to compute next-job buffers.
    jobs_by_crew: dict[str, list[Job]] = {}
    for job in jobs:
        jobs_by_crew.setdefault(job_to_crew[job.id], []).append(job)
    for crew_jobs in jobs_by_crew.values():
        crew_jobs.sort(key=lambda j: solver.Value(start_vars[j.id]))

    assignments: list[Assignment] = []
    for job in jobs:
        crew_id = job_to_crew[job.id]
        crew_jobs = jobs_by_crew[crew_id]
        idx = crew_jobs.index(job)
        next_job = crew_jobs[idx + 1] if idx + 1 < len(crew_jobs) else None

        checks = [
            "vehicle/driver qualifications are satisfied",
            "it does not overlap any other job assigned to this crew",
            "it starts and ends within its required arrival window and the crew's availability",
        ]
        if job.passenger_count > 0:
            checks.append(
                f"vehicle capacity is sufficient for {job.passenger_count} expected passengers"
            )
        max_continuous = crew_by_id[crew_id].driver.max_continuous_minutes
        if max_continuous is not None:
            checks.append(
                f"the driver's continuous-duty limit ({max_continuous} min) is not exceeded"
            )
        if crew_by_id[crew_id].busy_intervals:
            checks.append("it does not overlap this crew's other committed (locked) assignments")
        if minimum_buffer_minutes > 0:
            checks.append(
                f"at least {minimum_buffer_minutes} minutes of operational buffer remain "
                "before this crew's next job"
            )
        buffer_to_next = None
        if next_job is not None:
            deadhead = deadhead_estimator(
                job.location, next_job.location, crew_by_id[crew_id].vehicle
            )
            buffer_to_next = (
                solver.Value(start_vars[next_job.id]) - solver.Value(end_vars[job.id]) - deadhead
            )

        assignments.append(
            Assignment(
                job_id=job.id,
                crew_id=crew_id,
                start_minute=solver.Value(start_vars[job.id]),
                end_minute=solver.Value(end_vars[job.id]),
                explanation=Explanation(
                    job_id=job.id,
                    crew_id=crew_id,
                    hard_constraints_checked=tuple(checks),
                    buffer_minutes_to_next_job=buffer_to_next,
                    next_job_id=next_job.id if next_job else None,
                ),
            )
        )

    total_deadhead = 0
    for crew_id, crew_jobs in jobs_by_crew.items():
        vehicle = crew_by_id[crew_id].vehicle
        for earlier, later in zip(crew_jobs, crew_jobs[1:], strict=False):
            total_deadhead += deadhead_estimator(earlier.location, later.location, vehicle)
    total_buffer = sum(job.window.latest - solver.Value(end_vars[job.id]) for job in jobs)

    crews_used = sum(1 for c in crew_used.values() if solver.Value(c) == 1)
    logger.info(
        "Schedule found: %d job(s) assigned using %d crew(s) (of %d available)",
        len(assignments),
        crews_used,
        len(crews),
    )
    return SchedulingResult(
        assignments=tuple(assignments),
        crews_used=crews_used,
        total_deadhead_minutes=total_deadhead,
        total_arrival_buffer_minutes=total_buffer,
    )
