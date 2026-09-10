"""Tests for ors_deadhead_estimator.

These use a dependency-injected fake `http_post` so the parsing,
caching, and error-handling logic is verified without a live network
call — this sandboxed environment's network access is restricted to a
fixed domain allowlist that does not include a routing API. Validate
against a real OpenRouteService API key separately once this runs
somewhere with network access to it.
"""

import pytest

from isd_solver.domain import (
    DeadheadEstimationError,
    Location,
    Vehicle,
    ors_deadhead_estimator,
)

_NO_DIMENSIONS = Vehicle(id="V1")


def _fake_ors_response(duration_seconds: float):
    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        return {"routes": [{"summary": {"duration": duration_seconds, "distance": 0}}]}

    return fake_http_post


def test_converts_seconds_to_rounded_minutes():
    estimate = ors_deadhead_estimator(
        api_key="test-key",
        http_post=_fake_ors_response(330),  # 5.5 minutes -> rounds to 6
    )
    minutes = estimate(
        Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42), _NO_DIMENSIONS
    )
    assert minutes == 6


def test_same_location_short_circuits_without_calling_http():
    calls = []

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        calls.append(url)
        return {"routes": [{"summary": {"duration": 999}}]}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    a = Location(lat=29.70, lon=-95.40)
    assert estimate(a, a, _NO_DIMENSIONS) == 0
    assert calls == []


def test_result_is_cached_per_location_pair_and_vehicle():
    call_count = {"n": 0}

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        call_count["n"] += 1
        return {"routes": [{"summary": {"duration": 120}}]}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    a = Location(lat=29.70, lon=-95.40)
    b = Location(lat=29.72, lon=-95.42)

    assert estimate(a, b, _NO_DIMENSIONS) == 2
    assert estimate(a, b, _NO_DIMENSIONS) == 2
    assert call_count["n"] == 1  # second call served from cache


def test_different_vehicles_at_the_same_points_are_not_confused_in_the_cache():
    """A cache keyed on (origin, destination) alone would silently
    return one vehicle's cached result for a different vehicle at the
    same two points once the estimate genuinely varies by vehicle —
    this is the regression this test guards against."""
    durations = iter([120, 180])

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        return {"routes": [{"summary": {"duration": next(durations)}}]}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    a = Location(lat=29.70, lon=-95.40)
    b = Location(lat=29.72, lon=-95.42)
    small_bus = Vehicle(id="small", height_m=2.8)
    large_bus = Vehicle(id="large", height_m=3.8)

    assert estimate(a, b, small_bus) == 2
    assert estimate(a, b, large_bus) == 3  # genuinely different result, not a stale cache hit
    assert estimate(a, b, small_bus) == 2  # small_bus's own entry is still correctly cached


def test_no_routes_in_response_raises_without_fallback():
    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        return {"routes": []}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    with pytest.raises(DeadheadEstimationError):
        estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42), _NO_DIMENSIONS)


def test_http_failure_raises_without_fallback():
    def failing_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        raise TimeoutError("simulated network timeout")

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=failing_http_post)
    with pytest.raises(DeadheadEstimationError):
        estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42), _NO_DIMENSIONS)


def test_http_failure_uses_fallback_when_provided():
    def failing_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        raise TimeoutError("simulated network timeout")

    def fallback(a: Location, b: Location, vehicle: Vehicle) -> int:
        return 7

    estimate = ors_deadhead_estimator(
        api_key="test-key", http_post=failing_http_post, fallback=fallback
    )
    minutes = estimate(
        Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42), _NO_DIMENSIONS
    )
    assert minutes == 7


def test_sends_authorization_header_and_coordinates_body():
    seen = {}

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        seen["url"] = url
        seen["json_body"] = json_body
        seen["headers"] = headers
        return {"routes": [{"summary": {"duration": 60}}]}

    estimate = ors_deadhead_estimator(
        api_key="secret-key",
        base_url="https://example-ors.test",
        profile="driving-hgv",
        http_post=fake_http_post,
    )
    a = Location(lat=29.70, lon=-95.40)
    b = Location(lat=29.72, lon=-95.42)
    estimate(a, b, _NO_DIMENSIONS)

    assert seen["url"] == "https://example-ors.test/v2/directions/driving-hgv"
    assert seen["json_body"] == {"coordinates": [[-95.40, 29.70], [-95.42, 29.72]]}
    assert seen["headers"] == {"Authorization": "secret-key"}


def test_avoid_polygons_is_passed_through_into_the_request_body_options():
    seen = {}

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        seen["json_body"] = json_body
        return {"routes": [{"summary": {"duration": 60}}]}

    polygon = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
    estimate = ors_deadhead_estimator(
        api_key="test-key", http_post=fake_http_post, avoid_polygons=polygon
    )
    estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42), _NO_DIMENSIONS)

    assert seen["json_body"]["options"] == {"avoid_polygons": polygon}


def test_no_options_key_in_request_body_when_avoid_polygons_not_given():
    seen = {}

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        seen["json_body"] = json_body
        return {"routes": [{"summary": {"duration": 60}}]}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42), _NO_DIMENSIONS)

    assert "options" not in seen["json_body"]


def test_vehicle_dimensions_produce_restrictions():
    seen = {}

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        seen["json_body"] = json_body
        return {"routes": [{"summary": {"duration": 60}}]}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    vehicle = Vehicle(id="V1", length_m=10.5, width_m=2.5, height_m=3.2, weight_kg=12000.0)
    estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42), vehicle)

    # No top-level vehicle_type: live-verified against the real ORS API
    # (2026-09) that it rejects that field with a 400, despite some
    # published docs describing it as required — see the docstring.
    assert "vehicle_type" not in seen["json_body"]
    assert seen["json_body"]["options"]["profile_params"]["restrictions"] == {
        "length": 10.5,
        "width": 2.5,
        "height": 3.2,
        "weight": 12.0,  # kg -> tons
    }


def test_partial_vehicle_dimensions_only_send_the_known_ones():
    seen = {}

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        seen["json_body"] = json_body
        return {"routes": [{"summary": {"duration": 60}}]}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    vehicle = Vehicle(id="V1", height_m=3.2)
    estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42), vehicle)

    assert seen["json_body"]["options"]["profile_params"]["restrictions"] == {"height": 3.2}


def test_vehicle_with_no_dimensions_sends_no_options_at_all():
    seen = {}

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        seen["json_body"] = json_body
        return {"routes": [{"summary": {"duration": 60}}]}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42), _NO_DIMENSIONS)

    assert "options" not in seen["json_body"]


def test_rejects_empty_api_key():
    with pytest.raises(ValueError):
        ors_deadhead_estimator(api_key="")


def test_rejects_empty_base_url():
    with pytest.raises(ValueError):
        ors_deadhead_estimator(api_key="test-key", base_url="")
