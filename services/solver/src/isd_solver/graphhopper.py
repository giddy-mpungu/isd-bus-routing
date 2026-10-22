"""The district's own routing engine: GraphHopper with a school-bus profile
(services/routing, docs/routing-engine.md).

Every request carries a custom model built here:
  - the bus's own size (spec section 6): roads whose mapped height, width,
    length or weight limit it exceeds are closed to it;
  - areas to keep out of (spec sections 8 and 10): the district's hazard
    zones, the size-restricted zones this bus exceeds, and closures;
  - places that cost more to drive through (spec section 8): the
    district's difficult intersections and unsafe turns, still usable when
    there's no sensible way round (the engine can't price a turn by place,
    so the roads there are made less attractive instead);
  - turn costs (spec section 7): a right turn costs a little, a left more,
    a sharp turn more still, a left onto or off a main road (where it
    crosses several lanes of traffic) more again, and reversing onto
    another road is never allowed. Turning back along the same road (a
    U-turn) costs the profile's fixed u_turn_costs (config.yml), so it is
    used only when there's no other way, as at the end of a dead end.

Turn costs only choose the route; the times reported are driving times.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from isd_solver.directions import (
    MAX_WAYPOINTS,
    Directions,
    DirectionsError,
    DirectionStep,
    Leg,
    UTurn,
    areas_geojson,
)
from isd_solver.domain import (
    DeadheadEstimationError,
    DeadheadEstimator,
    Location,
    SizeRestriction,
    Vehicle,
    _default_http_post,
    _merge_avoid_polygons,
    avoid_polygons_geojson,
)

logger = logging.getLogger(__name__)

DEFAULT_PROFILE = "school_bus"

# Main roads: a left onto or off one crosses several lanes of traffic.
MAIN_ROADS = ("TRUNK", "PRIMARY", "SECONDARY")

# How much less attractive a road is inside a difficult-turn zone: driving
# through costs about this many times its time.
SLOW_ZONE_PRIORITY = 0.2

# GraphHopper's instruction signs for turning round.
U_TURN_SIGNS = {-98, -8, 8}
VIA_REACHED = 5
FINISH = 4


@dataclass(frozen=True)
class TurnRules:
    """Seconds added to a route's cost for each kind of turn (spec section
    7). Positive angles are to the right; anything sharper than 135
    degrees is a sharp turn."""

    right_s: int = 5
    sharp_right_s: int = 30
    left_s: int = 20
    sharp_left_s: int = 60
    # Extra, for a left onto or off a main road.
    main_road_left_s: int = 60

    def __post_init__(self) -> None:
        for name in ("right_s", "sharp_right_s", "left_s", "sharp_left_s", "main_road_left_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3600:
                raise ValueError(f"{name} must be whole seconds from 0 to 3600, got {value!r}")


def turn_penalty(rules: TurnRules) -> list[dict]:
    main = " || ".join(f"road_class == {c} || prev_road_class == {c}" for c in MAIN_ROADS)
    return [
        {"if": "change_angle > -25 && change_angle < 25", "add": "0"},
        {"else_if": "change_angle >= 25 && change_angle <= 135", "add": str(rules.right_s)},
        {"else_if": "change_angle > 135 && change_angle <= 180", "add": str(rules.sharp_right_s)},
        {
            "else_if": f"change_angle <= -25 && change_angle >= -135 && ({main})",
            "add": str(rules.left_s + rules.main_road_left_s),
        },
        {"else_if": "change_angle <= -25 && change_angle >= -135", "add": str(rules.left_s)},
        {
            "else_if": f"change_angle < -135 && change_angle >= -180 && ({main})",
            "add": str(rules.sharp_left_s + rules.main_road_left_s),
        },
        {"else_if": "change_angle < -135 && change_angle >= -180", "add": str(rules.sharp_left_s)},
        {"else": "", "add": "Infinity"},
    ]


def _polygons(geojson: dict | None) -> list[list]:
    if geojson is None:
        return []
    if geojson["type"] == "Polygon":
        return [geojson["coordinates"]]
    return list(geojson["coordinates"])


def custom_model(
    vehicle: Vehicle, avoid: dict | None, rules: TurnRules, slow: dict | None = None
) -> dict:
    """The per-request custom model for this bus. `avoid` (closed) and
    `slow` (costly to drive through) are GeoJSON Polygons or MultiPolygons
    (the same shape the ORS client takes)."""
    priority: list[dict] = []
    limits = []
    if vehicle.height_m is not None:
        limits.append(f"max_height < {vehicle.height_m:g}")
    if vehicle.width_m is not None:
        limits.append(f"max_width < {vehicle.width_m:g}")
    if vehicle.length_m is not None:
        limits.append(f"max_length < {vehicle.length_m:g}")
    if vehicle.weight_kg is not None:
        limits.append(f"max_weight < {vehicle.weight_kg / 1000.0:g}")  # tonnes
    if limits:
        priority.append({"if": " || ".join(limits), "multiply_by": "0"})

    model: dict = {"turn_penalty": turn_penalty(rules)}
    features: list[dict] = []
    for prefix, polygons, factor in (
        ("avoid", _polygons(avoid), "0"),
        ("slow", _polygons(slow), str(SLOW_ZONE_PRIORITY)),
    ):
        ids = [f"{prefix}_{i}" for i in range(len(polygons))]
        features += [
            {
                "type": "Feature",
                "id": area_id,
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": rings},
            }
            for area_id, rings in zip(ids, polygons, strict=True)
        ]
        if ids:
            priority.append({"if": " || ".join(f"in_{i}" for i in ids), "multiply_by": factor})
    if features:
        model["areas"] = {"type": "FeatureCollection", "features": features}
    if priority:
        model["priority"] = priority
    return model


def _avoid(
    fixed: dict | None, vehicle: Vehicle, size_restrictions: tuple[SizeRestriction, ...]
) -> tuple[dict | None, frozenset[SizeRestriction]]:
    violated = frozenset(r for r in size_restrictions if r.violated_by(vehicle))
    zones = avoid_polygons_geojson([z.location for z in violated]) if violated else None
    return _merge_avoid_polygons(fixed, zones), violated


def _message(exc: Exception) -> str:
    """GraphHopper's own reason, when it gave one (an HTTP 400 body)."""
    read = getattr(exc, "read", None)
    if callable(read):
        try:
            return str(json.loads(read().decode("utf-8")).get("message", exc))
        except Exception:  # noqa: BLE001 - only for a clearer message
            pass
    return str(exc)


def graphhopper_deadhead_estimator(
    base_url: str,
    *,
    profile: str = DEFAULT_PROFILE,
    avoid_polygons: dict | None = None,
    slow_points: list[Location] | None = None,
    size_restrictions: tuple[SizeRestriction, ...] = (),
    turn_rules: TurnRules | None = None,
    timeout_seconds: float = 10.0,
    http_post: Callable[[str, dict, dict[str, str], float], dict] | None = None,
    fallback: DeadheadEstimator | None = None,
) -> GraphHopperEstimator:
    """A DeadheadEstimator backed by the routing engine: the bus's driving
    minutes from a to b. Cached per (a, b, the bus's size, the zones it
    exceeds). On failure (engine down, a point off the map, no road
    between them) it uses `fallback`, logging a warning, or raises
    DeadheadEstimationError when there is none."""
    if not base_url:
        raise ValueError("base_url must be the routing engine's address")
    return GraphHopperEstimator(
        base_url.rstrip("/"),
        profile,
        avoid_polygons,
        avoid_polygons_geojson(list(slow_points)) if slow_points else None,
        size_restrictions,
        turn_rules or TurnRules(),
        timeout_seconds,
        http_post or _default_http_post,
        fallback,
    )


class GraphHopperEstimator:
    def __init__(
        self,
        base_url: str,
        profile: str,
        avoid_polygons: dict | None,
        slow: dict | None,
        size_restrictions: tuple[SizeRestriction, ...],
        rules: TurnRules,
        timeout_seconds: float,
        post: Callable[[str, dict, dict[str, str], float], dict],
        fallback: DeadheadEstimator | None,
    ) -> None:
        self._url = f"{base_url}/route"
        self._profile = profile
        self._fixed = avoid_polygons
        self._slow = slow
        self._size_restrictions = size_restrictions
        self._rules = rules
        self._timeout = timeout_seconds
        self._post = post
        self._fallback = fallback
        self._cache: dict[tuple, int] = {}

    def _key(self, a: Location, b: Location, vehicle: Vehicle) -> tuple:
        violated = frozenset(r for r in self._size_restrictions if r.violated_by(vehicle))
        size = (vehicle.length_m, vehicle.width_m, vehicle.height_m, vehicle.weight_kg)
        return (a, b, size, violated)

    def _fetch(self, a: Location, b: Location, vehicle: Vehicle) -> int:
        avoid, _ = _avoid(self._fixed, vehicle, self._size_restrictions)
        body = {
            "profile": self._profile,
            "points": [[a.lon, a.lat], [b.lon, b.lat]],
            "instructions": False,
            "calc_points": False,
            "custom_model": custom_model(vehicle, avoid, self._rules, self._slow),
        }
        payload = self._post(self._url, body, {}, self._timeout)
        paths = payload.get("paths") or []
        if not paths:
            raise DeadheadEstimationError(f"Routing engine found no route for {a} -> {b}")
        return int(round(float(paths[0]["time"]) / 60_000.0))

    def __call__(self, a: Location, b: Location, vehicle: Vehicle) -> int:
        if a == b:
            return 0
        key = self._key(a, b, vehicle)
        if key in self._cache:
            return self._cache[key]
        try:
            minutes = self._fetch(a, b, vehicle)
        except Exception as exc:  # noqa: BLE001 - network, HTTP and JSON errors alike
            if self._fallback is not None:
                logger.warning(
                    "Routing engine lookup failed for %s -> %s (%s); using fallback",
                    a,
                    b,
                    _message(exc),
                )
                return self._fallback(a, b, vehicle)
            raise DeadheadEstimationError(
                f"Routing engine couldn't time {a} -> {b}: {_message(exc)}"
            ) from exc
        self._cache[key] = minutes
        return minutes

    def prefetch(self, pairs: list[tuple[Location, Location, Vehicle]], workers: int = 8) -> None:
        """Time many legs at once, in parallel, before a solve asks for
        them one by one. Failures are left for the solve to meet (and fall
        back from) as usual."""
        todo: dict[tuple, tuple[Location, Location, Vehicle]] = {}
        for a, b, vehicle in pairs:
            if a != b:
                todo.setdefault(self._key(a, b, vehicle), (a, b, vehicle))
        todo = {k: v for k, v in todo.items() if k not in self._cache}
        if not todo:
            return

        def one(item: tuple[tuple, tuple[Location, Location, Vehicle]]) -> None:
            key, (a, b, vehicle) = item
            with contextlib.suppress(Exception):  # see the docstring
                self._cache[key] = self._fetch(a, b, vehicle)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, todo.items()))


def graphhopper_directions(
    base_url: str,
    waypoints: list[Location],
    vehicle: Vehicle,
    *,
    avoid_points: list[Location] | None = None,
    avoid_areas: list[tuple[Location, float]] | None = None,
    slow_points: list[Location] | None = None,
    size_restrictions: tuple[SizeRestriction, ...] = (),
    turn_rules: TurnRules | None = None,
    profile: str = DEFAULT_PROFILE,
    language: str = "en",
    timeout_seconds: float = 15.0,
    http_post: Callable[[str, dict, dict[str, str], float], dict] | None = None,
) -> Directions:
    """Turn-by-turn for this bus through its waypoints (spec section 9),
    keeping going at each stop rather than turning round there."""
    if not base_url:
        raise ValueError("base_url must be the routing engine's address")
    if len(waypoints) < 2:
        raise ValueError("directions need at least two waypoints")
    if len(waypoints) > MAX_WAYPOINTS:
        raise ValueError(f"directions take at most {MAX_WAYPOINTS} waypoints")

    fixed = _merge_avoid_polygons(
        avoid_polygons_geojson(list(avoid_points or [])) if avoid_points else None,
        areas_geojson(list(avoid_areas or [])),
    )
    avoid, _ = _avoid(fixed, vehicle, size_restrictions)
    body = {
        "profile": profile,
        "points": [[w.lon, w.lat] for w in waypoints],
        "instructions": True,
        "points_encoded": False,
        "locale": language,
        "pass_through": True,
        "custom_model": custom_model(
            vehicle,
            avoid,
            turn_rules or TurnRules(),
            avoid_polygons_geojson(list(slow_points)) if slow_points else None,
        ),
    }
    post = http_post or _default_http_post
    try:
        payload = post(f"{base_url.rstrip('/')}/route", body, {}, timeout_seconds)
        return parse_graphhopper(payload)
    except DirectionsError:
        raise
    except Exception as exc:  # noqa: BLE001 - network, HTTP and JSON errors alike
        raise DirectionsError(f"Routing engine directions failed: {_message(exc)}") from exc


def parse_graphhopper(payload: dict) -> Directions:
    try:
        path = payload["paths"][0]
        coordinates = [(float(lat), float(lon)) for lon, lat, *_ in path["points"]["coordinates"]]
        steps: list[DirectionStep] = []
        legs: list[Leg] = []
        u_turns: list[UTurn] = []
        points = path["points"]["coordinates"]
        leg, leg_distance, leg_time = 0, 0.0, 0.0
        for instruction in path.get("instructions", []):
            distance = float(instruction["distance"])
            seconds = float(instruction["time"]) / 1000.0
            sign = int(instruction["sign"])
            leg_distance += distance
            leg_time += seconds
            steps.append(
                DirectionStep(
                    instruction=str(instruction["text"]),
                    name=str(instruction.get("street_name") or ""),
                    distance_m=distance,
                    duration_s=seconds,
                    leg=leg,
                )
            )
            if sign in U_TURN_SIGNS:
                lon, lat, *_ = points[int(instruction["interval"][0])]
                u_turns.append(
                    UTurn(float(lat), float(lon), str(instruction.get("street_name") or ""))
                )
            if sign in (VIA_REACHED, FINISH):
                legs.append(Leg(leg_distance, leg_time))
                leg, leg_distance, leg_time = leg + 1, 0.0, 0.0
        return Directions(
            distance_m=float(path["distance"]),
            duration_s=float(path["time"]) / 1000.0,
            coordinates=coordinates,
            legs=legs,
            steps=steps,
            u_turns=u_turns,
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise DirectionsError(f"Unexpected directions response: {exc}") from exc
