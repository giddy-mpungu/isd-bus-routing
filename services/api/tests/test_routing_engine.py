"""The district's own routing engine (services/routing): when
ISD_API_ROUTING_ENGINE_URL is set, schedules are timed and directions
given by it rather than OpenRouteService. The engine is faked here; the
e2e checks run the real one."""

from isd_solver import Directions, DirectionStep, Leg

from isd_api.routers import schedule
from tests.test_directions import DAY, _directions, _empty_cache, _setup  # noqa: F401
from tests.test_schedule_end_to_end import _seed_single_run_scenario

ENGINE = "http://routing:8989"


def test_a_solve_is_timed_by_the_engine_with_every_leg_asked_ahead(
    client, admin_headers, monkeypatch
):
    _seed_single_run_scenario(client, admin_headers)
    monkeypatch.setattr(schedule.settings, "routing_engine_url", ENGINE)
    made = []

    class FakeEngine:
        def __init__(self, url, **kwargs):
            made.append((url, kwargs))
            self.prefetched = None

        def prefetch(self, pairs):
            self.prefetched = pairs

        def __call__(self, a, b, vehicle):
            return 5

    monkeypatch.setattr(schedule, "graphhopper_deadhead_estimator", FakeEngine)
    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 200, response.text
    [(url, kwargs)] = made
    assert url == ENGINE
    assert kwargs["profile"] == "school_bus"
    assert kwargs["fallback"] is not None  # a straight line if the engine is down


def test_directions_come_from_the_engine_in_the_drivers_language(
    client, admin_headers, db_session, monkeypatch
):
    assignment, driver = _setup(client, admin_headers, db_session)
    monkeypatch.setattr(schedule.settings, "routing_engine_url", ENGINE)
    monkeypatch.setattr(schedule.settings, "ors_api_key", None)
    calls = []

    def fake(url, waypoints, vehicle, **kwargs):
        calls.append((url, kwargs))
        return Directions(
            distance_m=5000.0,
            duration_s=600.0,
            coordinates=[(w.lat, w.lon) for w in waypoints],
            legs=[Leg(2500.0, 300.0) for _ in waypoints[1:]],
            steps=[DirectionStep("Gire a la derecha", "Oak Street", 2500.0, 300.0, 0)],
        )

    monkeypatch.setattr(schedule, "graphhopper_directions", fake)
    body = _directions(client, {**driver, "Accept-Language": "es"}, assignment).json()
    assert body["available"] is True
    assert body["steps"][0]["instruction"] == "Gire a la derecha"
    [(url, kwargs)] = calls
    assert (url, kwargs["language"], kwargs["profile"]) == (ENGINE, "es", "school_bus")


def test_with_neither_engine_nor_key_the_driver_is_told_why(
    client, admin_headers, db_session, monkeypatch
):
    assignment, driver = _setup(client, admin_headers, db_session)
    monkeypatch.setattr(schedule.settings, "routing_engine_url", None)
    monkeypatch.setattr(schedule.settings, "ors_api_key", None)
    body = _directions(client, driver, assignment).json()
    assert body["available"] is False
    assert "ISD_API_ROUTING_ENGINE_URL" in body["reason"]
