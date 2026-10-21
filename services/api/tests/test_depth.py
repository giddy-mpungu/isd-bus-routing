"""Depth from the October review: the route lock before departure (spec
section 4.4), the family's bus and place on the route (section 18), and
route deviations in the GPS report (section 20)."""

from isd_api.models import Role, User
from tests.conftest import auth_headers, login, make_user
from tests.test_directions import DAY
from tests.test_tracking import _report, _under_way, clock  # noqa: F401  (fixture)


def _rules(client, h, lock):
    response = client.put(
        "/ridership-rules",
        headers=h,
        json={
            "timezone": "America/Chicago",
            "am_cutoff_minute": None,
            "pm_cutoff_minute": None,
            "route_lock_minutes": lock,
        },
    )
    assert response.status_code == 200, response.text


def _route(client, h):
    [route] = client.get("/route-templates", headers=h).json()
    return route


def test_a_routes_stops_lock_before_its_run_leaves(
    client,
    admin_headers,
    db_session,
    clock,  # noqa: F811
):
    """07:30 in the district; the morning run is under way."""
    h = admin_headers
    _under_way(client, h, db_session)
    route = _route(client, h)
    stops = [
        {"stop_id": s["stop_id"], "minutes_from_start": s["minutes_from_start"]}
        for s in route["stops"]
    ]

    # No lock set: staff can still change the route.
    assert (
        client.put(
            f"/route-templates/{route['id']}/stops", headers=h, json={"stops": stops}
        ).status_code
        == 200
    )

    _rules(client, h, 30)
    refused = client.put(f"/route-templates/{route['id']}/stops", headers=h, json={"stops": stops})
    assert refused.status_code == 409
    assert "30-minute route lock" in refused.json()["detail"]
    applied = client.post(
        f"/route-templates/{route['id']}/stops/plan", headers=h, json={"apply": True}
    )
    assert applied.status_code == 409
    # Just looking at a plan isn't a change.
    preview = client.post(
        f"/route-templates/{route['id']}/stops/plan", headers=h, json={"apply": False}
    )
    assert preview.status_code == 200
    assert client.get("/ridership-rules", headers=h).json()["route_lock_minutes"] == 30


def test_the_family_sees_the_bus_and_where_their_stop_comes(
    client,
    admin_headers,
    db_session,
    clock,  # noqa: F811
):
    h = admin_headers
    _under_way(client, h, db_session)
    ana = next(s for s in client.get("/students", headers=h).json() if s["full_name"] == "Ana")
    make_user(db_session, email="pat@example.org", role=Role.PARENT)
    pat = db_session.query(User).filter(User.email == "pat@example.org").one()
    client.post(f"/students/{ana['id']}/guardians", headers=h, json={"user_id": pat.id})
    family = auth_headers(login(client, email="pat@example.org"))

    [child] = client.get("/students/my-family", headers=family, params={"service_date": DAY}).json()
    eta = child["am_eta"]
    # Ana's stop, Far, is the first of the two served today (Mid is skipped).
    assert (eta["bus_label"], eta["stop_position"], eta["stop_count"]) == ("Bus A", 1, 2)


def test_the_gps_report_says_how_far_each_position_was_from_the_route(
    client,
    admin_headers,
    db_session,
    clock,  # noqa: F811
):
    h = admin_headers
    _, driver, driver_id = _under_way(client, h, db_session)
    _report(client, driver, driver_id, 29.73, -95.401, 2)  # on the route
    _report(client, driver, driver_id, 29.73, -95.45, 1)  # nearly 5 km west

    report = client.get("/reports/positions", headers=h, params={"start": DAY, "end": DAY}).json()
    assert report["columns"][-2:] == ["Run", "Metres from route"]
    distances = [row[-1] for row in report["rows"]]
    assert distances[0] < 200
    assert 4500 < distances[1] < 5200
    assert report["rows"][0][-2] == "Riverside AM"
    assert report["summary"]["Over 800 m from the route"] == 1
