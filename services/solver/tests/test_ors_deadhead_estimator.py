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
    ors_deadhead_estimator,
)


def _fake_ors_response(duration_seconds: float):
    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        return {"routes": [{"summary": {"duration": duration_seconds, "distance": 0}}]}

    return fake_http_post


def test_converts_seconds_to_rounded_minutes():
    estimate = ors_deadhead_estimator(
        api_key="test-key",
        http_post=_fake_ors_response(330),  # 5.5 minutes -> rounds to 6
    )
    minutes = estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42))
    assert minutes == 6


def test_same_location_short_circuits_without_calling_http():
    calls = []

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        calls.append(url)
        return {"routes": [{"summary": {"duration": 999}}]}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    a = Location(lat=29.70, lon=-95.40)
    assert estimate(a, a) == 0
    assert calls == []


def test_result_is_cached_per_location_pair():
    call_count = {"n": 0}

    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        call_count["n"] += 1
        return {"routes": [{"summary": {"duration": 120}}]}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    a = Location(lat=29.70, lon=-95.40)
    b = Location(lat=29.72, lon=-95.42)

    assert estimate(a, b) == 2
    assert estimate(a, b) == 2
    assert call_count["n"] == 1  # second call served from cache


def test_no_routes_in_response_raises_without_fallback():
    def fake_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        return {"routes": []}

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=fake_http_post)
    with pytest.raises(DeadheadEstimationError):
        estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42))


def test_http_failure_raises_without_fallback():
    def failing_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        raise TimeoutError("simulated network timeout")

    estimate = ors_deadhead_estimator(api_key="test-key", http_post=failing_http_post)
    with pytest.raises(DeadheadEstimationError):
        estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42))


def test_http_failure_uses_fallback_when_provided():
    def failing_http_post(url: str, json_body: dict, headers: dict, timeout_seconds: float) -> dict:
        raise TimeoutError("simulated network timeout")

    def fallback(a: Location, b: Location) -> int:
        return 7

    estimate = ors_deadhead_estimator(
        api_key="test-key", http_post=failing_http_post, fallback=fallback
    )
    minutes = estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42))
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
    estimate(a, b)

    assert seen["url"] == "https://example-ors.test/v2/directions/driving-hgv"
    assert seen["json_body"] == {"coordinates": [[-95.40, 29.70], [-95.42, 29.72]]}
    assert seen["headers"] == {"Authorization": "secret-key"}


def test_rejects_empty_api_key():
    with pytest.raises(ValueError):
        ors_deadhead_estimator(api_key="")


def test_rejects_empty_base_url():
    with pytest.raises(ValueError):
        ors_deadhead_estimator(api_key="test-key", base_url="")
