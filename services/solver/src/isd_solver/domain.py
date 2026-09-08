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
    """

    id: str
    qualifications: frozenset[str] = field(default_factory=frozenset)
    nominal_capacity: int | None = None
    effective_capacity: int | None = None

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


DeadheadEstimator = Callable[[Location, Location], int]


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
    """

    if average_speed_kmh <= 0:
        raise ValueError("average_speed_kmh must be > 0")

    def estimate(a: Location, b: Location) -> int:
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

    def estimate(a: Location, b: Location) -> int:
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
                return fallback(a, b)
            raise DeadheadEstimationError(
                f"Failed to get routing-API deadhead estimate for {a} -> {b}: {exc}"
            ) from exc

        cache[key] = minutes
        return minutes

    return estimate


def ors_deadhead_estimator(
    api_key: str,
    base_url: str = "https://api.openrouteservice.org",
    profile: str = "driving-hgv",
    timeout_seconds: float = 5.0,
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
    truck-prohibited roads by default). IMPORTANT: this does **not**
    yet apply any *per-vehicle* restrictions (height/width/weight/length,
    also spec section 6) — every crew gets the same `driving-hgv`
    default regardless of its actual vehicle's dimensions. Doing so
    would require `DeadheadEstimator` to carry a `Vehicle` argument,
    which ripples into every `scheduler.py` call site — a deliberate
    follow-up, not part of this estimator. Turn/dead-end safety costs
    (section 7) and district-specific overrides (section 8) are also
    out of scope here — this is a point-to-point travel-time estimate,
    not a customizable routing graph.

    Results are cached in-memory per (origin, destination) pair for the
    lifetime of the returned estimator, since the scheduler's pairwise
    ordering logic may request the same pair more than once.

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
    cache: dict[tuple[Location, Location], int] = {}

    def estimate(a: Location, b: Location) -> int:
        if a == b:
            return 0
        key = (a, b)
        if key in cache:
            return cache[key]

        url = f"{base_url}/v2/directions/{profile}"
        body = {"coordinates": [[a.lon, a.lat], [b.lon, b.lat]]}
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
                return fallback(a, b)
            raise DeadheadEstimationError(
                f"Failed to get routing-API deadhead estimate for {a} -> {b}: {exc}"
            ) from exc

        cache[key] = minutes
        return minutes

    return estimate
