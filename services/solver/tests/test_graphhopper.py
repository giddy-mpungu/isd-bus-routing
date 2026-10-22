"""The district's own routing engine (isd_solver.graphhopper), with the HTTP
call injected; services/routing is exercised for real by the e2e checks."""

import pytest

from isd_solver import (
    DeadheadEstimationError,
    DirectionsError,
    Location,
    SizeRestriction,
    TurnRules,
    Vehicle,
    graphhopper_deadhead_estimator,
    graphhopper_directions,
)
from isd_solver.graphhopper import custom_model, turn_penalty

A, B, C = Location(29.74, -95.40), Location(29.71, -95.40), Location(29.70, -95.40)
BUS = Vehicle(id="1", length_m=12.2, width_m=2.6, height_m=3.2, weight_kg=14000)


def _engine(seconds=420.0):
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body))
        return {"paths": [{"time": seconds * 1000, "distance": 5000.0}]}

    return post, calls


def test_the_bus_is_timed_with_its_own_size_and_the_turn_rules():
    post, calls = _engine(seconds=420)
    estimate = graphhopper_deadhead_estimator("http://routing:8989/", http_post=post)
    assert estimate(A, B, BUS) == 7
    url, body = calls[0]
    assert url == "http://routing:8989/route"
    assert body["profile"] == "school_bus"
    assert body["points"] == [[-95.40, 29.74], [-95.40, 29.71]]
    [limits] = body["custom_model"]["priority"]
    assert limits == {
        "if": "max_height < 3.2 || max_width < 2.6 || max_length < 12.2 || max_weight < 14",
        "multiply_by": "0",
    }
    assert body["custom_model"]["turn_penalty"] == turn_penalty(TurnRules())


def test_each_leg_is_asked_once_and_the_same_place_is_free():
    post, calls = _engine()
    estimate = graphhopper_deadhead_estimator("http://routing:8989", http_post=post)
    estimate(A, B, BUS)
    estimate(A, B, BUS)
    assert estimate(A, A, BUS) == 0
    assert len(calls) == 1


def test_many_legs_can_be_timed_ahead_in_parallel():
    post, calls = _engine()
    estimate = graphhopper_deadhead_estimator("http://routing:8989", http_post=post)
    estimate.prefetch([(A, B, BUS), (B, C, BUS), (A, B, BUS), (C, C, BUS)])
    assert len(calls) == 2
    estimate(A, B, BUS)
    estimate(B, C, BUS)
    assert len(calls) == 2


def test_a_failure_falls_back_or_says_so():
    def down(url, body, headers, timeout):
        raise OSError("connection refused")

    def straight(a, b, vehicle):
        return 99

    assert (
        graphhopper_deadhead_estimator("http://routing:8989", http_post=down, fallback=straight)(
            A, B, BUS
        )
        == 99
    )
    with pytest.raises(DeadheadEstimationError, match="connection refused"):
        graphhopper_deadhead_estimator("http://routing:8989", http_post=down)(A, B, BUS)


def test_zones_to_avoid_close_those_roads():
    low_bridge = SizeRestriction(location=C, dimension="height_m", max_allowed=3.0)
    post, calls = _engine()
    estimate = graphhopper_deadhead_estimator(
        "http://routing:8989",
        avoid_polygons={
            "type": "MultiPolygon",
            "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]],
        },
        size_restrictions=(low_bridge,),
        http_post=post,
    )
    estimate(A, B, BUS)
    model = calls[0][1]["custom_model"]
    assert [f["id"] for f in model["areas"]["features"]] == ["avoid_0", "avoid_1"]
    assert model["priority"][-1] == {"if": "in_avoid_0 || in_avoid_1", "multiply_by": "0"}

    # A minibus fits under the bridge: only the standing zone.
    estimate(A, B, Vehicle(id="2", height_m=2.5))
    assert len(calls[1][1]["custom_model"]["areas"]["features"]) == 1


def test_turn_rules_rank_turns_and_never_reverse_onto_another_road():
    rules = TurnRules(right_s=1, sharp_right_s=2, left_s=3, sharp_left_s=4, main_road_left_s=10)
    adds = [r["add"] for r in turn_penalty(rules)]
    assert adds == ["0", "1", "2", "13", "3", "14", "4", "Infinity"]
    with pytest.raises(ValueError):
        TurnRules(left_s=-1)


def test_a_bus_of_unknown_size_sends_no_limits():
    assert "priority" not in custom_model(Vehicle(id="3"), None, TurnRules())


GH_RESPONSE = {
    "paths": [
        {
            "distance": 4500.0,
            "time": 540_000,
            "points": {"coordinates": [[-95.40, 29.74], [-95.401, 29.72], [-95.40, 29.70]]},
            "instructions": [
                {
                    "text": "Continue onto Oak Street",
                    "street_name": "Oak Street",
                    "distance": 3300.0,
                    "time": 400_000,
                    "sign": 0,
                },
                {"text": "Waypoint 1", "street_name": "", "distance": 0.0, "time": 0, "sign": 5},
                {
                    "text": "Turn right onto Elm Street",
                    "street_name": "Elm Street",
                    "distance": 1200.0,
                    "time": 140_000,
                    "sign": 2,
                },
                {
                    "text": "Arrive at destination",
                    "street_name": "",
                    "distance": 0.0,
                    "time": 0,
                    "sign": 4,
                },
            ],
        }
    ]
}


def test_directions_come_back_leg_by_leg():
    calls = []

    def post(url, body, headers, timeout):
        calls.append(body)
        return GH_RESPONSE

    found = graphhopper_directions(
        "http://routing:8989",
        [A, B, C],
        BUS,
        avoid_areas=[(C, 200.0)],
        language="es",
        http_post=post,
    )
    assert (found.distance_m, found.duration_s) == (4500.0, 540.0)
    assert found.coordinates[0] == (29.74, -95.40)
    assert [(leg.distance_m, leg.duration_s) for leg in found.legs] == [
        (3300.0, 400.0),
        (1200.0, 140.0),
    ]
    assert [(s.instruction, s.leg) for s in found.steps] == [
        ("Continue onto Oak Street", 0),
        ("Waypoint 1", 0),
        ("Turn right onto Elm Street", 1),
        ("Arrive at destination", 1),
    ]
    body = calls[0]
    assert (body["locale"], body["pass_through"], body["points_encoded"]) == ("es", True, False)
    assert body["custom_model"]["areas"]["features"][0]["id"] == "avoid_0"


def test_directions_failures_are_directions_errors():
    def refused(url, body, headers, timeout):
        raise OSError("no route")

    with pytest.raises(DirectionsError, match="no route"):
        graphhopper_directions("http://routing:8989", [A, B], BUS, http_post=refused)
    with pytest.raises(DirectionsError, match="Unexpected"):
        graphhopper_directions(
            "http://routing:8989", [A, B], BUS, http_post=lambda *args: {"paths": []}
        )


def test_difficult_places_cost_more_to_drive_through_but_stay_open():
    post, calls = _engine()
    estimate = graphhopper_deadhead_estimator(
        "http://routing:8989", slow_points=[C], http_post=post
    )
    estimate(A, B, BUS)
    model = calls[0][1]["custom_model"]
    assert [f["id"] for f in model["areas"]["features"]] == ["slow_0"]
    assert model["priority"][-1] == {"if": "in_slow_0", "multiply_by": "0.2"}


def test_directions_say_where_the_bus_turns_round():
    payload = {
        "paths": [
            {
                "distance": 900.0,
                "time": 120_000,
                "points": {"coordinates": [[-95.40, 29.74], [-95.385, 29.759], [-95.37, 29.77]]},
                "instructions": [
                    {
                        "text": "Continue",
                        "distance": 500.0,
                        "time": 60_000,
                        "sign": 0,
                        "interval": [0, 1],
                    },
                    {
                        "text": "Make a U-turn onto Rhode Place",
                        "street_name": "Rhode Place",
                        "distance": 400.0,
                        "time": 60_000,
                        "sign": -98,
                        "interval": [1, 2],
                    },
                    {
                        "text": "Arrive at destination",
                        "distance": 0.0,
                        "time": 0,
                        "sign": 4,
                        "interval": [2, 2],
                    },
                ],
            }
        ]
    }
    found = graphhopper_directions(
        "http://routing:8989", [A, B], BUS, http_post=lambda *args: payload
    )
    assert [(u.lat, u.lon, u.street) for u in found.u_turns] == [(29.759, -95.385, "Rhode Place")]
