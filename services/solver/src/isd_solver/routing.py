"""Ordering one route's stops and planning its times (spec sections 2,
3.1, 16), with OR-Tools' vehicle-routing solver.

A morning route picks students up and ends at the school; an afternoon
route starts at the school and drops them off. The plan visits every stop
once, in the order that takes the least time, subject to the ride-time
limit of the students at each stop (spec section 3.1 "maximum ride
time"): in the morning, from when the bus reaches their stop to when it
reaches school; in the afternoon, from leaving school to reaching their
stop. When no order meets every limit, the fastest order is returned with
the stops that break it named, rather than nothing.

Time at a stop (spec section 16 "student loading", "wheelchair loading")
is a fixed dwell plus a little per student and more per student with an
accommodation. Travel time between stops is an estimate supplied by the
caller; `straight_line_travel_seconds` is the default, and it is only an
estimate (see its docstring).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from isd_solver.domain import Location

TravelSeconds = Callable[[Location, Location], int]

# Loading and unloading (spec section 16).
DWELL_SECONDS_PER_STOP = 60
DWELL_SECONDS_PER_RIDER = 15
DWELL_SECONDS_PER_ACCOMMODATION = 180

_EARTH_RADIUS_KM = 6371.0


def straight_line_travel_seconds(
    average_speed_kmh: float = 30.0, detour_factor: float = 1.3
) -> TravelSeconds:
    """Haversine distance times a detour factor, at an average speed: 30
    km/h is the solver's documented suburban default and 1.3 a common rule
    of thumb for how much longer roads are than a straight line. An
    estimate for ordering stops, not a road-network travel time."""
    if average_speed_kmh <= 0 or detour_factor < 1:
        raise ValueError("average_speed_kmh must be > 0 and detour_factor >= 1")

    def seconds(a: Location, b: Location) -> int:
        lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
        h = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
        km = 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(h)) * detour_factor
        return int(round(km / average_speed_kmh * 3600))

    return seconds


@dataclass(frozen=True)
class StopDemand:
    stop_id: int
    location: Location
    riders: int = 0
    accommodation_riders: int = 0
    # The strictest ride limit among the stop's students; None when nobody
    # has one (an empty stop).
    max_ride_minutes: int | None = None

    def dwell_seconds(self) -> int:
        return (
            DWELL_SECONDS_PER_STOP
            + DWELL_SECONDS_PER_RIDER * self.riders
            + DWELL_SECONDS_PER_ACCOMMODATION * self.accommodation_riders
        )


@dataclass(frozen=True)
class PlannedStop:
    stop_id: int
    # Minutes after the route starts: the first stop (morning) or leaving
    # school (afternoon) is minute 0.
    minutes_from_start: int
    ride_minutes: int
    max_ride_minutes: int | None


@dataclass
class RoutePlan:
    stops: list[PlannedStop]
    # First stop to school (morning), or school to the last drop-off.
    total_minutes: int
    ride_limits_met: bool
    violations: list[str] = field(default_factory=list)


def _solve(
    nodes: list[Location],
    dwell: list[int],
    start: int,
    end: int,
    travel: TravelSeconds,
    limits: list[tuple[int, int]],
    direction: str,
    time_limit_seconds: int,
    riders: list[int] | None = None,
    ride_time_weight: int = 0,
) -> list[tuple[int, int]] | None:
    """[(node, arrival seconds)] along the best route, or None."""
    n = len(nodes)
    manager = pywrapcp.RoutingIndexManager(n, 1, [start], [end])
    model = pywrapcp.RoutingModel(manager)
    dummy = n - 1

    def transit(from_index: int, to_index: int) -> int:
        a, b = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
        if dummy in (a, b):
            return 0
        return travel(nodes[a], nodes[b]) + dwell[a]

    callback = model.RegisterTransitCallback(transit)
    model.SetArcCostEvaluatorOfAllVehicles(callback)
    model.AddDimension(callback, 0, 24 * 3600, True, "time")
    time = model.GetDimensionOrDie("time")
    for node, limit_seconds in limits:
        index = manager.NodeToIndex(node)
        if direction == "am":
            # From reaching this stop to reaching school.
            model.solver().Add(time.CumulVar(model.End(0)) - time.CumulVar(index) <= limit_seconds)
        else:
            # From leaving school to finishing this stop.
            model.solver().Add(
                time.CumulVar(index) + dwell[node] - time.CumulVar(model.Start(0)) <= limit_seconds
            )

    if ride_time_weight > 0 and riders:
        # Students' ride time, weighted against the route's own time (the
        # arc cost). The route starts at time 0, so in the afternoon a
        # stop's ride is its arrival time (plus dwell, a constant), and in
        # the morning it's the school arrival minus the stop's arrival:
        # the end weighted by everyone, less each stop by its riders.
        time.CumulVar(model.Start(0)).SetValue(0)
        everyone = sum(riders)
        if direction == "am":
            time.SetCumulVarSoftUpperBound(model.End(0), 0, ride_time_weight * everyone)
        for node, count in enumerate(riders):
            if count <= 0:
                continue
            index = manager.NodeToIndex(node)
            if direction == "am":
                time.SetCumulVarSoftLowerBound(index, 24 * 3600, ride_time_weight * count)
            else:
                time.SetCumulVarSoftUpperBound(index, 0, ride_time_weight * count)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    # Deterministic: the same stops always give the same plan.
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GREEDY_DESCENT
    params.time_limit.seconds = time_limit_seconds
    solution = model.SolveWithParameters(params)
    if solution is None:
        return None
    visits = []
    index = model.Start(0)
    while True:
        visits.append((manager.IndexToNode(index), solution.Value(time.CumulVar(index))))
        if model.IsEnd(index):
            break
        index = solution.Value(model.NextVar(index))
    return visits


def plan_route(
    school: Location,
    stops: list[StopDemand],
    *,
    direction: Literal["am", "pm"],
    travel_seconds: TravelSeconds | None = None,
    time_limit_seconds: int = 5,
    ride_time_weight: int = 0,
) -> RoutePlan:
    """The stop order and times for one route. ride_time_weight (spec
    section 2.2) weighs each student's minutes on the bus against the
    bus's own minutes: 0, the default, is simply the fastest route; 1
    counts a student-minute like a bus-minute."""
    if ride_time_weight < 0:
        raise ValueError("ride_time_weight must be >= 0")
    if direction not in ("am", "pm"):
        raise ValueError("direction must be 'am' or 'pm'")
    if not stops:
        return RoutePlan(stops=[], total_minutes=0, ride_limits_met=True)
    travel = travel_seconds or straight_line_travel_seconds()
    ordered_input = sorted(stops, key=lambda s: s.stop_id)

    # Nodes: the stops, then the school, then a free "anywhere" node the
    # route starts from (morning) or ends at (afternoon).
    nodes = [s.location for s in ordered_input] + [school, school]
    school_node, dummy = len(ordered_input), len(ordered_input) + 1
    dwell = [s.dwell_seconds() for s in ordered_input] + [0, 0]
    start, end = (dummy, school_node) if direction == "am" else (school_node, dummy)
    limits = [
        (i, s.max_ride_minutes * 60)
        for i, s in enumerate(ordered_input)
        if s.max_ride_minutes is not None
    ]

    riders = [s.riders for s in ordered_input] + [0, 0]
    visits = _solve(
        nodes,
        dwell,
        start,
        end,
        travel,
        limits,
        direction,
        time_limit_seconds,
        riders,
        ride_time_weight,
    )
    ride_limits_met = visits is not None
    if visits is None:
        visits = _solve(
            nodes,
            dwell,
            start,
            end,
            travel,
            [],
            direction,
            time_limit_seconds,
            riders,
            ride_time_weight,
        )
    if visits is None:  # pragma: no cover - an unconstrained tour always exists
        raise RuntimeError("no route found")

    stop_visits = [(node, t) for node, t in visits if node < len(ordered_input)]
    school_arrival = 0
    if direction == "am":
        origin = stop_visits[0][1]
        school_arrival = next(t for node, t in visits if node == school_node)
        total = school_arrival - origin
    else:
        origin = next(t for node, t in visits if node == school_node)
        last_node, last_time = stop_visits[-1]
        total = last_time + dwell[last_node] - origin

    planned: list[PlannedStop] = []
    violations: list[str] = []
    for node, t in stop_visits:
        stop = ordered_input[node]
        ride_seconds = (school_arrival - t) if direction == "am" else (t + dwell[node] - origin)
        ride = math.ceil(ride_seconds / 60)
        if stop.max_ride_minutes is not None and ride > stop.max_ride_minutes:
            violations.append(
                f"Stop {stop.stop_id}: {ride} min ride (limit {stop.max_ride_minutes} min)"
            )
        planned.append(
            PlannedStop(
                stop_id=stop.stop_id,
                minutes_from_start=(t - origin) // 60,
                ride_minutes=ride,
                max_ride_minutes=stop.max_ride_minutes,
            )
        )
    return RoutePlan(
        stops=planned,
        total_minutes=math.ceil(total / 60),
        ride_limits_met=ride_limits_met and not violations,
        violations=violations,
    )
