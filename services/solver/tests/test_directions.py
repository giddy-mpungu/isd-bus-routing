"""Turn-by-turn directions from OpenRouteService (isd_solver.directions),
with the HTTP call injected so no live key is needed."""

import pytest

from isd_solver import (
    Directions,
    DirectionsError,
    Location,
    SizeRestriction,
    Vehicle,
    ors_directions,
)

A, B, C = Location(29.74, -95.40), Location(29.71, -95.40), Location(29.70, -95.40)

RESPONSE = {
    "features": [
        {
            "geometry": {"coordinates": [[-95.40, 29.74], [-95.401, 29.72], [-95.40, 29.70]]},
            "properties": {
                "summary": {"distance": 4500.0, "duration": 540.0},
                "segments": [
                    {
                        "distance": 3300.0,
                        "duration": 400.0,
                        "steps": [
                            {
                                "instruction": "Head south on Oak Street",
                                "name": "Oak Street",
                                "distance": 3300.0,
                                "duration": 400.0,
                            },
                            {
                                "instruction": "Arrive at Oak Street",
                                "name": "-",
                                "distance": 0.0,
                                "duration": 0.0,
                            },
                        ],
                    },
                    {
                        "distance": 1200.0,
                        "duration": 140.0,
                        "steps": [
                            {
                                "instruction": "Turn right onto School Road",
                                "name": "School Road",
                                "distance": 1200.0,
                                "duration": 140.0,
                            }
                        ],
                    },
                ],
            },
        }
    ]
}


def fake(response=RESPONSE, error=None):
    calls = []

    def post(url, body, headers, timeout):
        calls.append({"url": url, "body": body, "headers": headers})
        if error is not None:
            raise error
        return response

    return post, calls


def test_directions_are_parsed_into_a_line_legs_and_steps():
    post, calls = fake()
    result = ors_directions("key", [A, B, C], Vehicle(id=1), http_post=post)
    assert isinstance(result, Directions)
    assert (result.distance_m, result.duration_s) == (4500.0, 540.0)
    assert result.coordinates == [(29.74, -95.40), (29.72, -95.401), (29.70, -95.40)]
    assert [(leg.distance_m, leg.duration_s) for leg in result.legs] == [
        (3300.0, 400.0),
        (1200.0, 140.0),
    ]
    assert [(s.instruction, s.name, s.leg) for s in result.steps] == [
        ("Head south on Oak Street", "Oak Street", 0),
        ("Arrive at Oak Street", "", 0),
        ("Turn right onto School Road", "School Road", 1),
    ]
    [call] = calls
    assert call["url"] == "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"
    assert call["headers"] == {"Authorization": "key"}
    body = call["body"]
    assert body["coordinates"] == [[-95.40, 29.74], [-95.40, 29.71], [-95.40, 29.70]]
    assert body["instructions"] is True
    # No turning round at a stop (spec section 7, U-turns).
    assert body["continue_straight"] is True
    assert "options" not in body  # no dimensions, nothing to avoid


def test_the_bus_dimensions_and_hazards_go_with_the_request():
    post, calls = fake()
    bus = Vehicle(id=1, length_m=12.2, width_m=2.6, height_m=3.2, weight_kg=14000)
    low_bridge = SizeRestriction(Location(29.72, -95.40), "height_m", 3.0)
    wide_enough = SizeRestriction(Location(29.73, -95.40), "width_m", 3.0)
    ors_directions(
        "key",
        [A, C],
        bus,
        avoid_points=[Location(29.705, -95.40)],
        size_restrictions=(low_bridge, wide_enough),
        http_post=post,
    )
    options = calls[0]["body"]["options"]
    assert options["profile_params"]["restrictions"] == {
        "length": 12.2,
        "width": 2.6,
        "height": 3.2,
        "weight": 14.0,
    }
    polygons = options["avoid_polygons"]
    # The hazard, and the bridge this bus is too tall for; not the width
    # limit it fits under.
    assert polygons["type"] == "MultiPolygon"
    assert len(polygons["coordinates"]) == 2


def test_failures_become_a_directions_error():
    post, _ = fake(error=OSError("connection refused"))
    with pytest.raises(DirectionsError, match="connection refused"):
        ors_directions("key", [A, C], Vehicle(id=1), http_post=post)
    odd, _ = fake(response={"features": []})
    with pytest.raises(DirectionsError, match="Unexpected directions response"):
        ors_directions("key", [A, C], Vehicle(id=1), http_post=odd)


def test_waypoints_and_key_are_checked_before_calling():
    post, calls = fake()
    with pytest.raises(ValueError):
        ors_directions("", [A, C], Vehicle(id=1), http_post=post)
    with pytest.raises(ValueError):
        ors_directions("key", [A], Vehicle(id=1), http_post=post)
    with pytest.raises(ValueError):
        ors_directions("key", [A] * 51, Vehicle(id=1), http_post=post)
    assert calls == []


def test_a_closure_becomes_a_ring_of_its_radius_around_its_centre():
    from isd_solver import area_polygon

    centre = Location(29.72, -95.40)
    ring = area_polygon(centre, 500, sides=12)
    assert len(ring) == 13 and ring[0] == ring[-1]
    # Every corner about 500 m from the centre.
    for lon, lat in ring[:-1]:
        dy = (lat - centre.lat) * 111_320
        dx = (lon - centre.lon) * 111_320 * 0.8686  # cos(29.72 degrees)
        assert abs((dx * dx + dy * dy) ** 0.5 - 500) < 5
    with pytest.raises(ValueError):
        area_polygon(centre, 0)


def test_closures_are_sent_as_areas_to_avoid():
    post, calls = fake()
    ors_directions(
        "key",
        [A, C],
        Vehicle(id="1"),
        avoid_points=[Location(29.705, -95.40)],
        avoid_areas=[(Location(29.72, -95.40), 300.0), (Location(29.73, -95.41), 150.0)],
        http_post=post,
    )
    polygons = calls[0]["body"]["options"]["avoid_polygons"]
    # The standing hazard plus the two closures.
    assert polygons["type"] == "MultiPolygon" and len(polygons["coordinates"]) == 3
