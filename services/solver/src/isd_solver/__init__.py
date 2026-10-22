"""isd_solver: multi-school crew scheduling engine (Phase 1).

Scope of this package, deliberately: given a set of Jobs (school runs
with required arrival windows) and a set of Crews (driver+vehicle
pairs), determine the minimum-crew feasible assignment where every hard
constraint (spec section 2.1) holds, or report infeasibility plainly.

See docs/adr/ and docs/domain-model.md at the repo root for the
reasoning behind the structure here.
"""

from isd_solver.directions import (
    Directions,
    DirectionsError,
    DirectionStep,
    Leg,
    NoRouteError,
    UTurn,
    area_polygon,
    areas_geojson,
    ors_directions,
)
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
    merge_avoid_polygons,
    ors_deadhead_estimator,
    osrm_deadhead_estimator,
    straight_line_deadhead_estimator,
)
from isd_solver.graphhopper import (
    GraphHopperEstimator,
    TurnRules,
    graphhopper_deadhead_estimator,
    graphhopper_directions,
)
from isd_solver.routing import (
    PlannedStop,
    RoutePlan,
    StopDemand,
    plan_route,
    straight_line_travel_seconds,
)
from isd_solver.scheduler import (
    Assignment,
    Explanation,
    InfeasibleResult,
    ObjectiveWeights,
    SchedulingResult,
    WorkRules,
    duty_limit,
    solve_multi_school_schedule,
)

__all__ = [
    "NoRouteError",
    "UTurn",
    "GraphHopperEstimator",
    "TurnRules",
    "graphhopper_deadhead_estimator",
    "graphhopper_directions",
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
    "merge_avoid_polygons",
    "ors_deadhead_estimator",
    "osrm_deadhead_estimator",
    "straight_line_deadhead_estimator",
    "Assignment",
    "Explanation",
    "InfeasibleResult",
    "ObjectiveWeights",
    "SchedulingResult",
    "WorkRules",
    "duty_limit",
    "solve_multi_school_schedule",
    "PlannedStop",
    "RoutePlan",
    "StopDemand",
    "plan_route",
    "straight_line_travel_seconds",
    "DirectionStep",
    "Directions",
    "DirectionsError",
    "Leg",
    "ors_directions",
    "area_polygon",
    "areas_geojson",
]
