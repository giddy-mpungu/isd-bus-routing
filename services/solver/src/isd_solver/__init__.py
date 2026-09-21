"""isd_solver: multi-school crew scheduling engine (Phase 1).

Scope of this package, deliberately: given a set of Jobs (school runs
with required arrival windows) and a set of Crews (driver+vehicle
pairs), determine the minimum-crew feasible assignment where every hard
constraint (spec section 2.1) holds, or report infeasibility plainly.

See docs/adr/ and docs/domain-model.md at the repo root for the
reasoning behind the structure here.
"""

from isd_solver.domain import (
    Crew,
    DeadheadEstimationError,
    DeadheadEstimator,
    Driver,
    Job,
    Location,
    School,
    SizeRestriction,
    TimeWindow,
    Vehicle,
    avoid_polygons_geojson,
    ors_deadhead_estimator,
    osrm_deadhead_estimator,
    straight_line_deadhead_estimator,
)
from isd_solver.scheduler import (
    Assignment,
    Explanation,
    InfeasibleResult,
    ObjectiveWeights,
    SchedulingResult,
    solve_multi_school_schedule,
)

__all__ = [
    "Crew",
    "DeadheadEstimationError",
    "DeadheadEstimator",
    "Driver",
    "Job",
    "Location",
    "School",
    "SizeRestriction",
    "TimeWindow",
    "Vehicle",
    "avoid_polygons_geojson",
    "ors_deadhead_estimator",
    "osrm_deadhead_estimator",
    "straight_line_deadhead_estimator",
    "Assignment",
    "Explanation",
    "InfeasibleResult",
    "ObjectiveWeights",
    "SchedulingResult",
    "solve_multi_school_schedule",
]
