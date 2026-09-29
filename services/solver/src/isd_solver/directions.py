"""Turn-by-turn directions for a bus through its stops (spec section 9
"bus-specific turn-by-turn navigation"), from OpenRouteService's
heavy-goods-vehicle profile.

The same bus-specific inputs as deadhead estimates (spec sections 6, 8):
the vehicle's length, width, height and weight as ORS restrictions, and
the district's hazard zones and the size-restricted zones this vehicle
exceeds as areas to avoid. `continue_straight` asks ORS not to turn round
at a stop (part of spec section 7's "prohibit or heavily penalize
U-turns"; a full turn-cost model needs a routing graph this system
doesn't own).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from isd_solver.domain import (
    Location,
    SizeRestriction,
    Vehicle,
    _default_http_post,
    _merge_avoid_polygons,
    avoid_polygons_geojson,
)

# ORS's limit on waypoints in one directions request.
MAX_WAYPOINTS = 50


class DirectionsError(RuntimeError):
    """ORS couldn't be reached, refused the request, or answered oddly."""


@dataclass(frozen=True)
class DirectionStep:
    instruction: str
    name: str
    distance_m: float
    duration_s: float
    # Which leg (waypoint i to i + 1) the step belongs to.
    leg: int


@dataclass(frozen=True)
class Leg:
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class Directions:
    distance_m: float
    duration_s: float
    # The route line, (lat, lon) in order.
    coordinates: list[tuple[float, float]]
    legs: list[Leg]
    steps: list[DirectionStep]


def vehicle_restrictions(vehicle: Vehicle) -> dict:
    """ORS `profile_params.restrictions` for the vehicle's dimensions."""
    restrictions: dict = {}
    if vehicle.length_m is not None:
        restrictions["length"] = vehicle.length_m
    if vehicle.width_m is not None:
        restrictions["width"] = vehicle.width_m
    if vehicle.height_m is not None:
        restrictions["height"] = vehicle.height_m
    if vehicle.weight_kg is not None:
        restrictions["weight"] = vehicle.weight_kg / 1000.0  # ORS expects tons
    return restrictions


def ors_directions(
    api_key: str,
    waypoints: list[Location],
    vehicle: Vehicle,
    *,
    avoid_points: list[Location] | None = None,
    size_restrictions: tuple[SizeRestriction, ...] = (),
    base_url: str = "https://api.openrouteservice.org",
    profile: str = "driving-hgv",
    timeout_seconds: float = 10.0,
    http_post: Callable[[str, dict, dict[str, str], float], dict] | None = None,
) -> Directions:
    if not api_key:
        raise ValueError("api_key must be a non-empty OpenRouteService API key")
    if len(waypoints) < 2:
        raise ValueError("directions need at least two waypoints")
    if len(waypoints) > MAX_WAYPOINTS:
        raise ValueError(f"directions take at most {MAX_WAYPOINTS} waypoints")

    violated = [z.location for z in size_restrictions if z.violated_by(vehicle)]
    avoid = _merge_avoid_polygons(
        avoid_polygons_geojson(list(avoid_points or [])) if avoid_points else None,
        avoid_polygons_geojson(violated) if violated else None,
    )
    body: dict = {
        "coordinates": [[w.lon, w.lat] for w in waypoints],
        "instructions": True,
        "language": "en",
        "units": "m",
        "continue_straight": True,
    }
    options: dict = {}
    if avoid is not None:
        options["avoid_polygons"] = avoid
    restrictions = vehicle_restrictions(vehicle)
    if restrictions:
        options["profile_params"] = {"restrictions": restrictions}
    if options:
        body["options"] = options

    post = http_post or _default_http_post
    try:
        payload = post(
            f"{base_url}/v2/directions/{profile}/geojson",
            body,
            {"Authorization": api_key},
            timeout_seconds,
        )
        return parse_directions(payload)
    except DirectionsError:
        raise
    except Exception as exc:  # noqa: BLE001 - network, HTTP and JSON errors alike
        raise DirectionsError(f"OpenRouteService directions failed: {exc}") from exc


def parse_directions(payload: dict) -> Directions:
    try:
        feature = payload["features"][0]
        properties = feature["properties"]
        coordinates = [
            (float(lat), float(lon)) for lon, lat, *_ in feature["geometry"]["coordinates"]
        ]
        legs: list[Leg] = []
        steps: list[DirectionStep] = []
        for index, segment in enumerate(properties.get("segments", [])):
            legs.append(Leg(float(segment["distance"]), float(segment["duration"])))
            for step in segment.get("steps", []):
                steps.append(
                    DirectionStep(
                        instruction=str(step["instruction"]),
                        name="" if step.get("name") in (None, "-") else str(step["name"]),
                        distance_m=float(step["distance"]),
                        duration_s=float(step["duration"]),
                        leg=index,
                    )
                )
        summary = properties["summary"]
        return Directions(
            distance_m=float(summary.get("distance", 0.0)),
            duration_s=float(summary.get("duration", 0.0)),
            coordinates=coordinates,
            legs=legs,
            steps=steps,
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise DirectionsError(f"Unexpected directions response: {exc}") from exc
