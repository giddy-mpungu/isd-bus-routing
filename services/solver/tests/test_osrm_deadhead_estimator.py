"""Tests for osrm_deadhead_estimator.

These use a dependency-injected fake `http_get` so the parsing,
caching, and error-handling logic is verified without a live network
call — this sandboxed environment's network access is restricted to a
fixed domain allowlist that does not include a routing API. Validate
against your real routing endpoint separately once this runs somewhere
with network access to it.
"""

import pytest

from isd_solver.domain import (
    DeadheadEstimationError,
    Location,
    osrm_deadhead_estimator,
)


def _fake_osrm_response(duration_seconds: float):
    def fake_http_get(url: str, timeout_seconds: float) -> dict:
        return {"routes": [{"duration": duration_seconds}], "code": "Ok"}

    return fake_http_get


def test_converts_seconds_to_rounded_minutes():
    estimate = osrm_deadhead_estimator(
        base_url="https://example-osrm.test",
        http_get=_fake_osrm_response(330),  # 5.5 minutes -> rounds to 6
    )
    minutes = estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42))
    assert minutes == 6


def test_same_location_short_circuits_without_calling_http():
    calls = []

    def fake_http_get(url: str, timeout_seconds: float) -> dict:
        calls.append(url)
        return {"routes": [{"duration": 999}]}

    estimate = osrm_deadhead_estimator(base_url="https://example-osrm.test", http_get=fake_http_get)
    a = Location(lat=29.70, lon=-95.40)
    assert estimate(a, a) == 0
    assert calls == []


def test_result_is_cached_per_location_pair():
    call_count = {"n": 0}

    def fake_http_get(url: str, timeout_seconds: float) -> dict:
        call_count["n"] += 1
        return {"routes": [{"duration": 120}]}

    estimate = osrm_deadhead_estimator(base_url="https://example-osrm.test", http_get=fake_http_get)
    a = Location(lat=29.70, lon=-95.40)
    b = Location(lat=29.72, lon=-95.42)

    assert estimate(a, b) == 2
    assert estimate(a, b) == 2
    assert call_count["n"] == 1  # second call served from cache


def test_no_routes_in_response_raises_without_fallback():
    def fake_http_get(url: str, timeout_seconds: float) -> dict:
        return {"routes": [], "code": "NoRoute"}

    estimate = osrm_deadhead_estimator(base_url="https://example-osrm.test", http_get=fake_http_get)
    with pytest.raises(DeadheadEstimationError):
        estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42))


def test_http_failure_raises_without_fallback():
    def failing_http_get(url: str, timeout_seconds: float) -> dict:
        raise TimeoutError("simulated network timeout")

    estimate = osrm_deadhead_estimator(
        base_url="https://example-osrm.test", http_get=failing_http_get
    )
    with pytest.raises(DeadheadEstimationError):
        estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42))


def test_http_failure_uses_fallback_when_provided():
    def failing_http_get(url: str, timeout_seconds: float) -> dict:
        raise TimeoutError("simulated network timeout")

    def fallback(a: Location, b: Location) -> int:
        return 7

    estimate = osrm_deadhead_estimator(
        base_url="https://example-osrm.test", http_get=failing_http_get, fallback=fallback
    )
    minutes = estimate(Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42))
    assert minutes == 7


def test_rejects_empty_base_url():
    with pytest.raises(ValueError):
        osrm_deadhead_estimator(base_url="")
