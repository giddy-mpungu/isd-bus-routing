"""Ordering a route's stops and planning its times (isd_solver.routing)."""

import pytest

from isd_solver import Location, StopDemand, plan_route, straight_line_travel_seconds

SCHOOL = Location(29.70, -95.40)


def minutes_apart(minutes: int):
    """A travel function where each step of 0.01 degrees takes `minutes`."""

    def travel(a: Location, b: Location) -> int:
        steps = round((abs(a.lat - b.lat) + abs(a.lon - b.lon)) / 0.01)
        return steps * minutes * 60

    return travel


def stop(stop_id, lat, riders=0, limit=None, accommodation=0):
    return StopDemand(stop_id, Location(lat, -95.40), riders, accommodation, limit)


def test_a_morning_route_visits_the_far_stop_first_and_ends_at_school():
    # A line of stops north of school: the only sensible order is far to near.
    stops = [stop(1, 29.71), stop(2, 29.73), stop(3, 29.72)]
    plan = plan_route(SCHOOL, stops, direction="am", travel_seconds=minutes_apart(2))
    assert [s.stop_id for s in plan.stops] == [2, 3, 1]
    # 1 minute dwell per stop, 2 minutes per hop: 0, 3, 6, then school at 9.
    assert [s.minutes_from_start for s in plan.stops] == [0, 3, 6]
    assert plan.total_minutes == 9
    assert [s.ride_minutes for s in plan.stops] == [9, 6, 3]
    assert plan.ride_limits_met and plan.violations == []


def test_an_afternoon_route_starts_at_school_and_drops_the_near_stop_first():
    stops = [stop(1, 29.71), stop(2, 29.73), stop(3, 29.72)]
    plan = plan_route(SCHOOL, stops, direction="pm", travel_seconds=minutes_apart(2))
    assert [s.stop_id for s in plan.stops] == [1, 3, 2]
    assert [s.minutes_from_start for s in plan.stops] == [2, 5, 8]
    # The last drop-off finishes after its 1-minute dwell.
    assert plan.total_minutes == 9
    assert [s.ride_minutes for s in plan.stops] == [3, 6, 9]


def test_loading_time_grows_with_riders_and_accommodations():
    quick = stop(1, 29.71)
    busy = stop(1, 29.71, riders=4, accommodation=1)
    travel = minutes_apart(2)
    assert plan_route(SCHOOL, [quick], direction="am", travel_seconds=travel).total_minutes == 3
    # 60 + 4*15 + 180 seconds of dwell = 5 minutes, then 2 minutes to school.
    assert plan_route(SCHOOL, [busy], direction="am", travel_seconds=travel).total_minutes == 7


def test_ride_limits_can_change_the_order():
    # Without limits the fastest morning order is 2, 3, 1 (far to near), and
    # stop 2's rider rides 10 minutes (their stop's 75 s of loading, then
    # three hops and two stops). With an 8-minute limit, stop 2 has to come
    # later: at best, straight to school after it, 75 s + 6 min.
    stops = [stop(1, 29.71), stop(2, 29.73, riders=1, limit=8), stop(3, 29.72)]
    travel = minutes_apart(2)
    free = plan_route(
        SCHOOL,
        [stop(1, 29.71), stop(2, 29.73, riders=1), stop(3, 29.72)],
        direction="am",
        travel_seconds=travel,
    )
    assert [s.stop_id for s in free.stops] == [2, 3, 1]
    assert {s.stop_id: s.ride_minutes for s in free.stops}[2] == 10

    plan = plan_route(SCHOOL, stops, direction="am", travel_seconds=travel)
    assert [s.stop_id for s in plan.stops] != [2, 3, 1]
    assert {s.stop_id: s.ride_minutes for s in plan.stops}[2] <= 8
    assert plan.ride_limits_met and plan.violations == []
    # Meeting the limit costs time overall.
    assert plan.total_minutes > free.total_minutes


def test_an_impossible_limit_still_gives_the_fastest_route_and_says_why():
    stops = [stop(1, 29.71), stop(2, 29.75, riders=1, limit=3)]
    plan = plan_route(SCHOOL, stops, direction="am", travel_seconds=minutes_apart(2))
    assert [s.stop_id for s in plan.stops] == [2, 1]
    assert plan.ride_limits_met is False
    # 75 s loading at stop 2, 8 min to stop 1, 1 min there, 2 min to school.
    assert plan.violations == ["Stop 2: 13 min ride (limit 3 min)"]


def test_the_plan_is_the_same_every_time():
    stops = [stop(i, 29.70 + ((i * 7) % 11) / 100) for i in range(1, 12)]
    first = plan_route(SCHOOL, stops, direction="am")
    again = plan_route(SCHOOL, list(reversed(stops)), direction="am")
    assert [s.stop_id for s in first.stops] == [s.stop_id for s in again.stops]


def test_no_stops_is_an_empty_plan():
    plan = plan_route(SCHOOL, [], direction="pm")
    assert (plan.stops, plan.total_minutes, plan.ride_limits_met) == ([], 0, True)


def test_the_straight_line_estimate_is_distance_times_a_detour_at_an_average_speed():
    travel = straight_line_travel_seconds(average_speed_kmh=30, detour_factor=1.3)
    # 0.1 degrees of latitude is about 11.12 km: 14.46 km of road at 30 km/h.
    assert travel(Location(29.7, -95.4), Location(29.8, -95.4)) == pytest.approx(1735, abs=3)
    with pytest.raises(ValueError):
        straight_line_travel_seconds(detour_factor=0.5)
    with pytest.raises(ValueError):
        plan_route(SCHOOL, [], direction="noon")  # type: ignore[arg-type]


def test_weighting_ride_time_drops_the_crowded_stop_first():
    """Spec section 2.2: with no weight the bus takes the fastest route; weighing
    students' ride time, it serves the stop where most children wait first."""
    school = Location(29.70, -95.40)
    near_one = StopDemand(stop_id=1, location=Location(29.70, -95.39), riders=1)
    far_ten = StopDemand(stop_id=2, location=Location(29.70, -95.415), riders=10)

    fastest = plan_route(school, [near_one, far_ten], direction="pm")
    assert [s.stop_id for s in fastest.stops] == [1, 2]

    for direction in ("pm", "am"):
        kinder = plan_route(school, [near_one, far_ten], direction=direction, ride_time_weight=1)
        order = [s.stop_id for s in kinder.stops]
        # Afternoon: drop the ten first. Morning: pick them up last.
        assert order == ([2, 1] if direction == "pm" else [1, 2])


def test_ride_time_weight_cant_be_negative():
    with pytest.raises(ValueError):
        plan_route(Location(29.7, -95.4), [], direction="am", ride_time_weight=-1)
