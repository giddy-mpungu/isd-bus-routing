"""Tests for avoid_polygons_geojson (spec section 8's wiring point into
isd_solver.domain.ors_deadhead_estimator's options.avoid_polygons)."""

import pytest

from isd_solver.domain import Location, avoid_polygons_geojson


def test_empty_points_returns_none():
    assert avoid_polygons_geojson([]) is None


def test_single_point_produces_a_closed_five_point_ring():
    point = Location(lat=29.70, lon=-95.40)
    result = avoid_polygons_geojson([point], buffer_degrees=0.001)

    assert result["type"] == "MultiPolygon"
    assert len(result["coordinates"]) == 1
    ring = result["coordinates"][0][0]
    assert len(ring) == 5
    assert ring[0] == ring[-1]  # closed ring
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    assert min(lons) == pytest.approx(-95.401)
    assert max(lons) == pytest.approx(-95.399)
    assert min(lats) == pytest.approx(29.699)
    assert max(lats) == pytest.approx(29.701)


def test_multiple_points_produce_one_ring_each():
    points = [Location(lat=29.70, lon=-95.40), Location(lat=29.72, lon=-95.42)]
    result = avoid_polygons_geojson(points)

    assert result["type"] == "MultiPolygon"
    assert len(result["coordinates"]) == 2
