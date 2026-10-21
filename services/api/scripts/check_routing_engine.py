"""Check the routing engine answers (docs/routing-engine.md).

Asks it, the way a schedule solve and a driver's directions do, for a
school bus's route between two points in the demo district (or the two
points given), with the bus's size and the turn rules, and prints the
distance, the time and the first few instructions. Exits 1 when it can't.

Usage:
    python scripts/check_routing_engine.py [LAT,LON LAT,LON]
"""

from __future__ import annotations

import sys

from isd_solver import (
    DirectionsError,
    Location,
    Vehicle,
    graphhopper_deadhead_estimator,
    graphhopper_directions,
)

from isd_api.config import settings

# Two schools of the fictional demo district, in central Houston.
DEMO = (Location(29.7445, -95.3995), Location(29.7735, -95.37))
# A typical Type C school bus.
BUS = Vehicle(id="check", length_m=12.2, width_m=2.6, height_m=3.2, weight_kg=14000)


def _point(text: str) -> Location:
    lat, lon = (float(part) for part in text.split(","))
    return Location(lat, lon)


def main(argv: list[str]) -> int:
    url = settings.routing_engine_url
    if not url:
        print("ISD_API_ROUTING_ENGINE_URL isn't set.", file=sys.stderr)
        return 1
    a, b = (_point(argv[0]), _point(argv[1])) if len(argv) == 2 else DEMO
    try:
        minutes = graphhopper_deadhead_estimator(url, profile=settings.routing_engine_profile)(
            a, b, BUS
        )
        found = graphhopper_directions(url, [a, b], BUS, profile=settings.routing_engine_profile)
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        print(f"The routing engine at {url} didn't answer: {exc}", file=sys.stderr)
        return 1
    if not 0 < found.distance_m < 1_000_000 or not found.steps:
        print(f"The routing engine's answer looks wrong: {found}", file=sys.stderr)
        return 1
    print(f"{found.distance_m / 1000:.1f} km, about {minutes} min, {len(found.steps)} steps:")
    for step in found.steps[:5]:
        print(f"  {step.instruction} ({step.distance_m:.0f} m)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except DirectionsError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
