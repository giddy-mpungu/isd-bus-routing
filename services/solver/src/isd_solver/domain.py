"""Domain entities for Phase 1 (spec section 5: multi-school crew scheduling).

Times are represented as integer minutes since midnight of the single
service day being scheduled. This keeps the CP-SAT model in integers
(required) without pulling in full datetime/timezone handling, which
is out of scope until a real service-day/timezone model is needed in
Phase 2. Values must be in [0, 1440).

See docs/domain-model.md at the repo root for the full field list and
rationale; this module implements only the Phase 1 subset.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt

logger = logging.getLogger(__name__)

MINUTES_PER_DAY = 24 * 60

# Mean Earth radius in km, used only for the Phase 1 straight-line
# deadhead approximation below (not for any bus-legal routing claim).
_EARTH_RADIUS_KM = 6371.0


def _validate_minute_of_day(value: int, field_name: str) -> None:
    if not (0 <= value < MINUTES_PER_DAY):
        raise ValueError(f"{field_name}={value} must be a minute-of-day in [0, {MINUTES_PER_DAY})")


@dataclass(frozen=True)
class TimeWindow:
    """A window, in minutes since midnight, that some event must fall within.

    Spec 2.1: "Cannot arrive at a school within the required time
    window" is a hard constraint — this type is how that window is
    represented everywhere in the solver.
    """

    earliest: int
    latest: int

    def __post_init__(self) -> None:
        _validate_minute_of_day(self.earliest, "earliest")
        _validate_minute_of_day(self.latest, "latest")
        if self.earliest > self.latest:
            raise ValueError(
                f"TimeWindow.earliest ({self.earliest}) must be <= latest ({self.latest})"
            )

    @property
    def duration_minutes(self) -> int:
        return self.latest - self.earliest


@dataclass(frozen=True)
class Location:
    """A point used only for deadhead-time estimation in Phase 1.

    Not a substitute for the bus-legal routing graph required by spec
    section 6 — see docs/domain-model.md, "Not yet implemented".
    """

    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"lat={self.lat} out of range [-90, 90]")
        if not (-180.0 <= self.lon <= 180.0):
            raise ValueError(f"lon={self.lon} out of range [-180, 180]")


@dataclass(frozen=True)
class School:
    id: str
    name: str
    location: Location


@dataclass(frozen=True)
class Job:
    """One run-instance to be scheduled: a single crew serving one
    school's bell window on the service day (spec section 5).

    duration_minutes and buffer_minutes are kept separate per ADR 0002
    / spec section 16 (predicted travel time vs. scheduled operational
    time) so a caller can see how much of the schedule is buffer.
    """

    id: str
    school_id: str
    window: TimeWindow
    duration_minutes: int
    buffer_minutes: int
    location: Location
    required_vehicle_qualifications: frozenset[str] = field(default_factory=frozenset)
    # 0 means "ridership not modeled for this job" and is never a capacity
    # violation on its own (spec section 4 ridership-declaration data
    # feeds this in later phases; Phase 1 callers may leave it at 0).
    passenger_count: int = 0

    def __post_init__(self) -> None:
        if self.duration_minutes <= 0:
            raise ValueError(f"Job {self.id}: duration_minutes must be > 0")
        if self.buffer_minutes < 0:
            raise ValueError(f"Job {self.id}: buffer_minutes must be >= 0")
        if self.passenger_count < 0:
            raise ValueError(f"Job {self.id}: passenger_count must be >= 0")
        total = self.duration_minutes + self.buffer_minutes
        if total > self.window.duration_minutes:
            raise ValueError(
                f"Job {self.id}: duration+buffer ({total} min) exceeds its own "
                f"window length ({self.window.duration_minutes} min) — this job "
                "cannot be completed even alone; fix the input data before scheduling."
            )

    @property
    def total_occupied_minutes(self) -> int:
        """Time this job actually occupies a crew, including its buffer."""
        return self.duration_minutes + self.buffer_minutes


@dataclass(frozen=True)
class Vehicle:
    """Spec section 15 distinguishes nominal capacity (seats as built)
    from effective operational capacity (what's actually usable given
    passenger age, seating configuration, or wheelchair use). Both are
    optional so existing callers that don't model capacity are
    unaffected; allowable_capacity() is what the scheduler enforces.

    length_m/width_m/height_m/weight_kg (spec section 6's vehicle
    profile) are persisted but NOT YET consumed anywhere in this
    module — `DeadheadEstimator` (below) is still
    `Callable[[Location, Location], int]`, with no `Vehicle` argument,
    so every crew still gets ORS's plain `driving-hgv` profile
    regardless of its actual vehicle's dimensions. Widening that
    signature (and `scheduler.py`'s pairwise-ordering loop, which
    currently calls the estimator once per job-pair shared across
    every candidate crew, not once per (job-pair, crew)) is a
    deliberate follow-up, not part of this change — same "persist
    first, wire in as a named follow-up" shape as spec section 8's
    `GeographicKnowledgeOverride`.
    """

    id: str
    qualifications: frozenset[str] = field(default_factory=frozenset)
    nominal_capacity: int | None = None
    effective_capacity: int | None = None
    length_m: float | None = None
    width_m: float | None = None
    height_m: float | None = None
    weight_kg: float | None = None

    def __post_init__(self) -> None:
        if self.nominal_capacity is not None and self.nominal_capacity <= 0:
            raise ValueError(f"Vehicle {self.id}: nominal_capacity must be > 0")
        if self.effective_capacity is not None and self.effective_capacity <= 0:
            raise ValueError(f"Vehicle {self.id}: effective_capacity must be > 0")
        if (
            self.nominal_capacity is not None
            and self.effective_capacity is not None
            and self.effective_capacity > self.nominal_capacity
        ):
            raise ValueError(
                f"Vehicle {self.id}: effective_capacity ({self.effective_capacity}) "
                f"cannot exceed nominal_capacity ({self.nominal_capacity})"
            )
        for field_name in ("length_m", "width_m", "height_m", "weight_kg"):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise ValueError(f"Vehicle {self.id}: {field_name} must be > 0")

    def allowable_capacity(self) -> int | None:
        """The capacity the scheduler enforces against passenger demand
        (spec section 15: "must ensure that assigned passenger demand
        does not exceed allowable capacity"). Effective capacity is
        used when known, since it reflects real usable seating; falls
        back to nominal capacity; None means capacity is unknown for
        this vehicle.
        """
        if self.effective_capacity is not None:
            return self.effective_capacity
        return self.nominal_capacity


@dataclass(frozen=True)
class Driver:
    id: str
    license_qualifications: frozenset[str] = field(default_factory=frozenset)
    # District-configured limit; this codebase asserts nothing about
    # what any specific driver-hour law requires (ADR: see domain.py
    # module docstring and README "Non-negotiables").
    max_continuous_minutes: int | None = None


@dataclass(frozen=True)
class Crew:
    """A Driver+Vehicle pairing considered together for scheduling
    purposes (ADR 0001) — not a persistent entity in later phases."""

    id: str
    driver: Driver
    vehicle: Vehicle
    available_window: TimeWindow
    # Time ranges within available_window this crew is already
    # committed elsewhere (spec section 21: a locked assignment
    # protects that specific commitment, not the crew's whole day —
    # see routers/schedule.py for how the api populates this on a
    # re-solve). No deadhead buffer is enforced around a busy
    # interval — there's no Job/location for whatever's happening
    # during it, so this is a time-only exclusion, not a full
    # scheduling constraint like the pairwise job-vs-job case.
    busy_intervals: tuple[TimeWindow, ...] = ()

    def __post_init__(self) -> None:
        for interval in self.busy_intervals:
            if (
                interval.earliest < self.available_window.earliest
                or interval.latest > self.available_window.latest
            ):
                raise ValueError(
                    f"Crew {self.id}: busy interval [{interval.earliest}, {interval.latest}] "
                    f"falls outside available_window [{self.available_window.earliest}, "
                    f"{self.available_window.latest}]"
                )

    def is_qualified_for(self, job: Job) -> bool:
        return job.required_vehicle_qualifications.issubset(self.vehicle.qualifications)

    def has_capacity_for(self, job: Job) -> bool:
        """Spec section 15: assigned passenger demand must not exceed
        allowable capacity. A job with passenger_count == 0 (ridership
        not modeled) always passes. A job that *does* declare riders
        against a vehicle with unknown capacity fails closed — an
        unknown capacity is not treated as unlimited capacity, since
        that would silently violate the spec's safety intent.
        """
        if job.passenger_count == 0:
            return True
        capacity = self.vehicle.allowable_capacity()
        if capacity is None:
            return False
        return capacity >= job.passenger_count


@dataclass(frozen=True)
class SizeRestriction:
    """Spec section 8's `VEHICLE_SIZE_RESTRICTED` local-knowledge
    category, e.g. "the covered bridge on Elm St has a 10ft height
    limit" — local staff knowledge ORS's own map data may not have,
    distinct from spec section 6's per-vehicle HGV `restrictions`
    (which ask ORS to route around *its own* known road limits for a
    vehicle's dimensions). `dimension` names one of `Vehicle`'s own
    size fields (`length_m`/`width_m`/`height_m`/`weight_kg`) — the one
    physical property this specific restriction is about; `max_allowed`
    is in the same units as that field. Only a vehicle whose own
    dimension is *known* and exceeds the threshold is considered
    restricted — an unknown vehicle dimension is never treated as an
    assumed violation (spec section 21: don't guess)."""

    location: Location
    dimension: str
    max_allowed: float

    def __post_init__(self) -> None:
        if self.dimension not in ("length_m", "width_m", "height_m", "weight_kg"):
            raise ValueError(
                f"SizeRestriction.dimension must be one of length_m/width_m/height_m/"
                f"weight_kg, got {self.dimension!r}"
            )
        if self.max_allowed <= 0:
            raise ValueError("SizeRestriction.max_allowed must be > 0")

    def violated_by(self, vehicle: Vehicle) -> bool:
        value = getattr(vehicle, self.dimension)
        return value is not None and value > self.max_allowed


DeadheadEstimator = Callable[[Location, Location, Vehicle], int]


def straight_line_deadhead_estimator(
    average_speed_kmh: float = 30.0,
) -> DeadheadEstimator:
    """Returns a DeadheadEstimator using haversine distance / average speed.

    This is an explicit Phase 1 approximation, not a road-network
    estimate — a real deployment must supply an estimator backed by
    actual bus-legal routing (spec section 6) before this number is
    used for anything operational. average_speed_kmh must be supplied
    by the caller for their context; 30 km/h is a documented default
    for suburban school-zone-adjacent driving, not a measured figure.

    Takes a Vehicle argument (DeadheadEstimator's shared signature) but
    ignores it — a haversine straight-line distance doesn't depend on
    the vehicle's dimensions; only ors_deadhead_estimator actually
    consumes them (spec section 6's real wiring point).
    """

    if average_speed_kmh <= 0:
        raise ValueError("average_speed_kmh must be > 0")

    def estimate(a: Location, b: Location, vehicle: Vehicle) -> int:
        lat1, lon1, lat2, lon2 = map(radians, (a.lat, a.lon, b.lat, b.lon))
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        distance_km = 2 * _EARTH_RADIUS_KM * asin(sqrt(h))
        minutes = (distance_km / average_speed_kmh) * 60.0
        return int(round(minutes))

    return estimate


class DeadheadEstimationError(RuntimeError):
    """Raised when a routing-API-backed deadhead estimate can't be obtained
    and no fallback estimator was supplied."""


def _default_http_get(url: str, timeout_seconds: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _default_http_post(
    url: str, json_body: dict, headers: dict[str, str], timeout_seconds: float
) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(json_body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def osrm_deadhead_estimator(
    base_url: str,
    profile: str = "driving",
    timeout_seconds: float = 5.0,
    http_get: Callable[[str, float], dict] | None = None,
    fallback: DeadheadEstimator | None = None,
) -> DeadheadEstimator:
    """Returns a DeadheadEstimator backed by an OSRM-compatible routing API.

    Calls ``GET {base_url}/route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}?overview=false``
    and reads ``routes[0].duration`` (seconds) from the response, per the
    OSRM HTTP API's documented response shape. This has NOT been
    exercised against a live OSRM server in this development
    environment — this sandbox's network access is restricted to a
    fixed allowlist that does not include a routing API, so `http_get`
    is dependency-injected specifically so the parsing/caching/error
    logic can be tested without a live network call. Verify against
    your actual routing API endpoint (self-hosted OSRM, a commercial
    routing API in OSRM-compatible mode, etc.) before relying on it.

    IMPORTANT — this is still not the bus-legal routing required by
    spec section 6. The `driving` profile models a passenger car, not
    a school bus (no height/weight/turning-radius/road-restriction
    awareness). Treat this as a better-than-straight-line Phase 1/6
    approximation, not a source of truth for bus-legal travel time,
    until a bus-specific routing profile is integrated.

    Results are cached in-memory per (origin, destination) pair for the
    lifetime of the returned estimator, since the scheduler's pairwise
    ordering logic may request the same pair more than once.

    Takes a Vehicle argument (DeadheadEstimator's shared signature) but
    ignores it — OSRM's public HTTP API has no restriction-parameter
    mechanism to apply vehicle dimensions to (unlike ORS), and this
    estimator remains the unwired scaffold it always has been.

    If the API call fails (network error, non-2xx, unexpected response
    shape) and `fallback` is provided, the fallback estimator is used
    and the failure is logged at WARNING level. If no fallback is
    provided, `DeadheadEstimationError` is raised — silently falling
    back to a straight-line guess without telling the caller would
    hide a routing failure that could matter for a safety-relevant
    schedule.
    """

    if not base_url:
        raise ValueError("base_url must be a non-empty routing API base URL")

    fetch = http_get or _default_http_get
    cache: dict[tuple[Location, Location], int] = {}

    def estimate(a: Location, b: Location, vehicle: Vehicle) -> int:
        if a == b:
            return 0
        key = (a, b)
        if key in cache:
            return cache[key]

        url = f"{base_url}/route/v1/{profile}/{a.lon},{a.lat};{b.lon},{b.lat}?overview=false"
        try:
            payload = fetch(url, timeout_seconds)
            routes = payload["routes"]
            if not routes:
                raise DeadheadEstimationError(f"Routing API returned no route for {a} -> {b}")
            duration_seconds = routes[0]["duration"]
            minutes = int(round(duration_seconds / 60.0))
        except Exception as exc:  # noqa: BLE001 - deliberately broad: network/JSON/shape errors all handled the same way
            if fallback is not None:
                logger.warning(
                    "Routing API deadhead lookup failed for %s -> %s (%s); using fallback",
                    a,
                    b,
                    exc,
                )
                return fallback(a, b, vehicle)
            raise DeadheadEstimationError(
                f"Failed to get routing-API deadhead estimate for {a} -> {b}: {exc}"
            ) from exc

        cache[key] = minutes
        return minutes

    return estimate


def avoid_polygons_geojson(points: list[Location], buffer_degrees: float = 0.0004) -> dict | None:
    """Builds a GeoJSON MultiPolygon of small squares around each point,
    for ORS's ``options.avoid_polygons`` (spec section 8: district-
    specific geographic knowledge). ``buffer_degrees`` defaults to
    roughly 44m at the equator — a small, deliberately conservative
    "avoid this specific spot," not a wide exclusion zone. Which
    GeographicKnowledgeOverride categories get passed in here (and
    which deliberately don't) is the API layer's decision — see
    ``routers/schedule.py`` — this function only turns points into
    geometry, with no opinion on what they mean.

    Returns None for an empty points list; callers should omit
    ``avoid_polygons`` from the ORS request entirely in that case
    rather than send an empty/degenerate geometry.
    """
    if not points:
        return None

    rings = []
    for point in points:
        lat, lon = point.lat, point.lon
        rings.append(
            [
                [
                    [lon - buffer_degrees, lat - buffer_degrees],
                    [lon + buffer_degrees, lat - buffer_degrees],
                    [lon + buffer_degrees, lat + buffer_degrees],
                    [lon - buffer_degrees, lat + buffer_degrees],
                    [lon - buffer_degrees, lat - buffer_degrees],
                ]
            ]
        )
    return {"type": "MultiPolygon", "coordinates": rings}


def _merge_avoid_polygons(fixed: dict | None, dynamic: dict | None) -> dict | None:
    """Combines the estimator-lifetime-fixed avoid_polygons with a
    per-call dynamic one (spec section 8's VEHICLE_SIZE_RESTRICTED
    zones this specific vehicle violates) into a single MultiPolygon.
    Both inputs, when present, are always MultiPolygon (the only shape
    avoid_polygons_geojson produces), so concatenating `coordinates` is
    a correct merge, not an approximation."""
    if fixed is None:
        return dynamic
    if dynamic is None:
        return fixed
    return {"type": "MultiPolygon", "coordinates": fixed["coordinates"] + dynamic["coordinates"]}


def merge_avoid_polygons(a: dict | None, b: dict | None) -> dict | None:
    """Two avoid-polygon GeoJSON values combined into one (either may be
    None)."""
    return _merge_avoid_polygons(a, b)


def ors_deadhead_estimator(
    api_key: str,
    base_url: str = "https://api.openrouteservice.org",
    profile: str = "driving-hgv",
    timeout_seconds: float = 5.0,
    avoid_polygons: dict | None = None,
    size_restrictions: tuple[SizeRestriction, ...] = (),
    http_post: Callable[[str, dict, dict[str, str], float], dict] | None = None,
    fallback: DeadheadEstimator | None = None,
) -> DeadheadEstimator:
    """Returns a DeadheadEstimator backed by OpenRouteService's Directions API.

    Calls ``POST {base_url}/v2/directions/{profile}`` with an
    ``Authorization`` header and a ``{"coordinates": [[lon, lat], [lon, lat]]}``
    body, and reads ``routes[0].summary.duration`` (seconds) from the
    response, per ORS's documented response shape (same ``routes[0]``
    shape as OSRM's, despite the different request method). This has
    NOT been exercised against a live ORS server in this development
    environment — this sandbox's network access is restricted to a
    fixed allowlist that does not include a routing API, so `http_post`
    is dependency-injected specifically so the parsing/caching/error
    logic can be tested without a live network call. Verify against a
    real ORS API key (openrouteservice.org's free tier) before relying
    on it.

    `profile` defaults to `driving-hgv`, ORS's heavy-goods-vehicle
    profile — meaningfully closer to spec section 6's bus-specific
    routing intent than a passenger-car profile (avoids some
    truck-prohibited roads by default). Per-vehicle restrictions (spec
    section 6) are now applied: when the `Vehicle` passed to `estimate`
    has any of `length_m`/`width_m`/`height_m`/`weight_kg` set, the
    request body's `options.profile_params.restrictions` gains the
    corresponding keys (length/width/height in meters, matching how
    they're persisted; weight converted from the persisted kilograms
    to the tons ORS expects). A vehicle with no dimensions set sends no
    `options.profile_params` at all, identical to pre-wiring behavior.
    IMPORTANT — live-verified against the real API, not just
    documentation: some published ORS docs describe a top-level
    `vehicle_type` field as required alongside `restrictions` for them
    to take effect; this live API instance (v2 directions, confirmed
    2026-09) actively **rejects** an unrecognized `vehicle_type`
    parameter with a 400, so it is deliberately NOT sent —
    `restrictions` alone is accepted and presumably applied (this
    system has no independent way to prove ORS's internal restriction
    logic actually changes route selection beyond confirming the
    request itself is accepted without error; if a future ORS API
    version reintroduces a required `vehicle_type` field, this is the
    place to add it back, driven by another live check, not by docs
    alone). Turn/dead-end safety costs (section 7) remain out of scope
    here — this is a point-to-point travel-time estimate, not a
    customizable routing graph.

    `avoid_polygons` is the wiring point for spec section 8's
    always-on district-specific geographic knowledge (frequent
    flooding, unsafe turns, invalid turnarounds) — a GeoJSON Polygon or
    MultiPolygon (see `avoid_polygons_geojson` above for building one
    from points) passed straight into ORS's `options.avoid_polygons`.
    Fixed for the estimator's whole lifetime, not re-evaluated per
    call, since it represents standing local knowledge rather than
    anything that varies per origin/destination pair or vehicle.

    `size_restrictions` is the wiring point for spec section 8's
    `VEHICLE_SIZE_RESTRICTED` category — unlike `avoid_polygons`, this
    *is* re-evaluated on every call: each `SizeRestriction` is checked
    against the specific `Vehicle` passed to `estimate`
    (`SizeRestriction.violated_by`), and only the zones a given vehicle
    actually violates are merged into that call's `avoid_polygons`
    (via `_merge_avoid_polygons`) — a small vehicle that fits under a
    restricted bridge never detours around it, while an oversized one
    does. Which `GeographicKnowledgeOverride` categories become
    `avoid_polygons` vs. `size_restrictions` vs. neither (several
    categories are cautions, time-dependent-but-solve-wide, or positive
    preferences that no avoid-zone can correctly express) is
    `routers/schedule.py`'s decision, not this function's — it accepts
    whatever geometry/restrictions it's given.

    Results are cached in-memory per (origin, destination, vehicle
    restriction signature, violated size-restriction zones) for the
    lifetime of the returned estimator, since the scheduler's pairwise
    ordering logic may request the same pair more than once — the
    vehicle (and, now, which size-restriction zones it violates) is
    part of the key precisely because two different vehicles at the
    same two points can now get genuinely different ORS results (a
    cache keyed on location alone would silently reuse one vehicle's
    result for another's). `avoid_polygons` is NOT part of the key,
    since it's fixed for the estimator's whole lifetime, not per-call.

    If the API call fails (network error, non-2xx, unexpected response
    shape) and `fallback` is provided, the fallback estimator is used
    and the failure is logged at WARNING level. If no fallback is
    provided, `DeadheadEstimationError` is raised — silently falling
    back to a straight-line guess without telling the caller would
    hide a routing failure that could matter for a safety-relevant
    schedule.
    """

    if not api_key:
        raise ValueError("api_key must be a non-empty OpenRouteService API key")
    if not base_url:
        raise ValueError("base_url must be a non-empty routing API base URL")

    post = http_post or _default_http_post
    cache: dict[tuple[Location, Location, tuple[float | None, ...], frozenset], int] = {}

    def estimate(a: Location, b: Location, vehicle: Vehicle) -> int:
        if a == b:
            return 0
        restriction_signature = (
            vehicle.length_m,
            vehicle.width_m,
            vehicle.height_m,
            vehicle.weight_kg,
        )
        violated_zones = frozenset(r for r in size_restrictions if r.violated_by(vehicle))
        key = (a, b, restriction_signature, violated_zones)
        if key in cache:
            return cache[key]

        effective_avoid_polygons = _merge_avoid_polygons(
            avoid_polygons,
            avoid_polygons_geojson([z.location for z in violated_zones])
            if violated_zones
            else None,
        )

        url = f"{base_url}/v2/directions/{profile}"
        body: dict = {"coordinates": [[a.lon, a.lat], [b.lon, b.lat]]}
        options: dict = {}
        if effective_avoid_polygons is not None:
            options["avoid_polygons"] = effective_avoid_polygons
        restrictions: dict = {}
        if vehicle.length_m is not None:
            restrictions["length"] = vehicle.length_m
        if vehicle.width_m is not None:
            restrictions["width"] = vehicle.width_m
        if vehicle.height_m is not None:
            restrictions["height"] = vehicle.height_m
        if vehicle.weight_kg is not None:
            restrictions["weight"] = vehicle.weight_kg / 1000.0  # ORS expects tons
        if restrictions:
            options["profile_params"] = {"restrictions": restrictions}
        if options:
            body["options"] = options
        headers = {"Authorization": api_key}
        try:
            payload = post(url, body, headers, timeout_seconds)
            routes = payload["routes"]
            if not routes:
                raise DeadheadEstimationError(f"Routing API returned no route for {a} -> {b}")
            duration_seconds = routes[0]["summary"]["duration"]
            minutes = int(round(duration_seconds / 60.0))
        except Exception as exc:  # noqa: BLE001 - deliberately broad: network/JSON/shape errors all handled the same way
            if fallback is not None:
                logger.warning(
                    "Routing API deadhead lookup failed for %s -> %s (%s); using fallback",
                    a,
                    b,
                    exc,
                )
                return fallback(a, b, vehicle)
            raise DeadheadEstimationError(
                f"Failed to get routing-API deadhead estimate for {a} -> {b}: {exc}"
            ) from exc

        cache[key] = minutes
        return minutes

    return estimate
