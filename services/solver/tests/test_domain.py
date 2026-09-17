import pytest

from isd_solver.domain import (
    Crew,
    Driver,
    Job,
    Location,
    SizeRestriction,
    TimeWindow,
    Vehicle,
    straight_line_deadhead_estimator,
)


def test_time_window_rejects_inverted_range():
    with pytest.raises(ValueError):
        TimeWindow(earliest=100, latest=50)


def test_time_window_rejects_out_of_range_minute():
    with pytest.raises(ValueError):
        TimeWindow(earliest=-1, latest=50)
    with pytest.raises(ValueError):
        TimeWindow(earliest=0, latest=1440)


def test_job_rejects_duration_plus_buffer_exceeding_window():
    with pytest.raises(ValueError):
        Job(
            id="J1",
            school_id="S1",
            window=TimeWindow(earliest=360, latest=370),  # 10 min window
            duration_minutes=20,
            buffer_minutes=5,
            location=Location(lat=29.7, lon=-95.4),
        )


def test_crew_qualification_check():
    vehicle = Vehicle(id="V1", qualifications=frozenset({"wheelchair"}))
    driver = Driver(id="D1", license_qualifications=frozenset({"CDL_B"}))
    crew = Crew(
        id="C1",
        driver=driver,
        vehicle=vehicle,
        available_window=TimeWindow(earliest=0, latest=1439),
    )
    job_needs_wheelchair = Job(
        id="J1",
        school_id="S1",
        window=TimeWindow(earliest=360, latest=410),
        duration_minutes=30,
        buffer_minutes=5,
        location=Location(lat=29.7, lon=-95.4),
        required_vehicle_qualifications=frozenset({"wheelchair"}),
    )
    job_needs_lift = Job(
        id="J2",
        school_id="S1",
        window=TimeWindow(earliest=360, latest=410),
        duration_minutes=30,
        buffer_minutes=5,
        location=Location(lat=29.7, lon=-95.4),
        required_vehicle_qualifications=frozenset({"lift"}),
    )
    assert crew.is_qualified_for(job_needs_wheelchair) is True
    assert crew.is_qualified_for(job_needs_lift) is False


def test_crew_accepts_busy_interval_within_available_window():
    crew = Crew(
        id="C1",
        driver=Driver(id="D1"),
        vehicle=Vehicle(id="V1"),
        available_window=TimeWindow(earliest=0, latest=1439),
        busy_intervals=(TimeWindow(earliest=360, latest=410),),
    )
    assert crew.busy_intervals == (TimeWindow(earliest=360, latest=410),)


def test_crew_rejects_busy_interval_outside_available_window():
    with pytest.raises(ValueError):
        Crew(
            id="C1",
            driver=Driver(id="D1"),
            vehicle=Vehicle(id="V1"),
            available_window=TimeWindow(earliest=400, latest=1439),
            busy_intervals=(TimeWindow(earliest=360, latest=410),),  # starts before the window
        )


def test_vehicle_accepts_dimension_fields():
    vehicle = Vehicle(id="V1", length_m=10.5, width_m=2.5, height_m=3.2, weight_kg=12000.0)
    assert vehicle.length_m == 10.5
    assert vehicle.width_m == 2.5
    assert vehicle.height_m == 3.2
    assert vehicle.weight_kg == 12000.0


def test_vehicle_dimension_fields_default_to_none():
    vehicle = Vehicle(id="V1")
    assert vehicle.length_m is None
    assert vehicle.width_m is None
    assert vehicle.height_m is None
    assert vehicle.weight_kg is None


@pytest.mark.parametrize("field_name", ["length_m", "width_m", "height_m", "weight_kg"])
def test_vehicle_rejects_non_positive_dimension(field_name):
    with pytest.raises(ValueError):
        Vehicle(id="V1", **{field_name: 0})
    with pytest.raises(ValueError):
        Vehicle(id="V1", **{field_name: -1})


def test_straight_line_deadhead_estimator_symmetric_and_positive():
    estimate = straight_line_deadhead_estimator(average_speed_kmh=30.0)
    a = Location(lat=29.7604, lon=-95.3698)  # Houston
    b = Location(lat=29.8, lon=-95.4)
    vehicle = Vehicle(id="V1")
    minutes_ab = estimate(a, b, vehicle)
    minutes_ba = estimate(b, a, vehicle)
    assert minutes_ab == minutes_ba
    assert minutes_ab > 0


def test_deadhead_estimator_zero_for_same_location():
    estimate = straight_line_deadhead_estimator()
    a = Location(lat=29.7604, lon=-95.3698)
    assert estimate(a, a, Vehicle(id="V1")) == 0


def test_deadhead_estimator_rejects_non_positive_speed():
    with pytest.raises(ValueError):
        straight_line_deadhead_estimator(average_speed_kmh=0)


def test_size_restriction_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        SizeRestriction(
            location=Location(lat=29.7, lon=-95.4), dimension="turning_radius_m", max_allowed=5.0
        )


def test_size_restriction_rejects_non_positive_max_allowed():
    with pytest.raises(ValueError):
        SizeRestriction(location=Location(lat=29.7, lon=-95.4), dimension="height_m", max_allowed=0)


def test_size_restriction_violated_by_a_vehicle_exceeding_the_threshold():
    restriction = SizeRestriction(
        location=Location(lat=29.7, lon=-95.4), dimension="height_m", max_allowed=3.0
    )
    tall_bus = Vehicle(id="V1", height_m=3.5)
    short_bus = Vehicle(id="V2", height_m=2.8)
    assert restriction.violated_by(tall_bus) is True
    assert restriction.violated_by(short_bus) is False


def test_size_restriction_not_violated_when_vehicle_dimension_is_unknown():
    """Spec section 21: don't guess. A vehicle with no persisted
    height_m can't be proven to violate a height restriction, so it
    isn't treated as restricted just because the data is missing."""
    restriction = SizeRestriction(
        location=Location(lat=29.7, lon=-95.4), dimension="height_m", max_allowed=3.0
    )
    unknown_height_bus = Vehicle(id="V1")
    assert restriction.violated_by(unknown_height_bus) is False
