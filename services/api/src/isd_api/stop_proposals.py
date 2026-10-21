"""Proposing bus stops from students' homes (spec section 3.1).

Covers what this system has data for: each student's walking limit by
grade band, the district's minimum stop spacing, reusing stops that
already exist, curb-to-curb stops for specialized transportation, and
warnings near the district's own reported hazards (spec section 8).
Road width, traffic volume, speed limits, visibility, curves, hills,
railroad crossings and safe crossings need road-network data this system
doesn't have, so a proposal is a starting point for staff: they approve,
reject or relocate each one (spec section 3.1's last line).

Distances are straight-line. Real walking distance is never shorter, so a
proposal can look walkable here and be a longer walk on the ground; staff
check it on the map.

The steps, for the eligible students of one school who have a home on
file and no stop yet:
  1. Specialized transportation: a curb stop at the home.
  2. Within walking limit of an existing stop: that stop (the nearest).
  3. Everyone else, grouped greedily: repeatedly pick the home from which
     the most remaining students are within their own limits, place the
     stop where the group's walks add up to least (spec section 2.2) if
     that's still within everyone's limit (else at the group's centre, else
     at that home), and take them out.

The district's walking weight (Setup, Rules & optimization) shortens
every limit by 5% a step before any of this: shorter walks, more stops.
  4. Spacing: a new stop closer than the minimum spacing to another stop
     joins it when all its students can walk there; otherwise it's kept,
     with a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from isd_api.eligibility import miles_between

# Hazards (spec section 8 categories) worth a warning near a stop.
HAZARD_CATEGORIES = {
    "frequent_flooding": "frequent flooding",
    "difficult_intersection": "a difficult intersection",
    "unsafe_turn": "an unsafe turn",
    "invalid_turnaround": "an unsuitable turnaround",
    "other": "a reported hazard",
}
HAZARD_WARNING_MILES = 0.1


@dataclass(frozen=True)
class Home:
    student_id: int
    lat: float
    lon: float
    walk_limit_miles: float
    specialized: bool = False


@dataclass(frozen=True)
class Place:
    id: int
    label: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Hazard:
    category: str
    note: str
    lat: float
    lon: float


@dataclass
class Proposal:
    kind: str  # "new", "existing" or "curb"
    lat: float
    lon: float
    student_ids: list[int]
    stop_id: int | None = None
    label: str = ""
    warnings: list[str] = field(default_factory=list)


def _dist(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    return miles_between(a_lat, a_lon, b_lat, b_lon)


def _within(home: Home, lat: float, lon: float) -> bool:
    return _dist(home.lat, home.lon, lat, lon) <= home.walk_limit_miles + 1e-9


def shortest_walks(points: list[tuple[float, float]]) -> tuple[float, float]:
    """The point the group's straight-line walks add up to least (the
    geometric median, by Weiszfeld's method), starting from the centre."""
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    for _ in range(100):
        weights = []
        for p_lat, p_lon in points:
            d = _dist(lat, lon, p_lat, p_lon)
            if d < 1e-9:  # standing on a home: stay (good enough here)
                return lat, lon
            weights.append(1 / d)
        total = sum(weights)
        new_lat = sum(w * p[0] for w, p in zip(weights, points, strict=True)) / total
        new_lon = sum(w * p[1] for w, p in zip(weights, points, strict=True)) / total
        if abs(new_lat - lat) < 1e-9 and abs(new_lon - lon) < 1e-9:
            break
        lat, lon = new_lat, new_lon
    return lat, lon


def hazard_warnings(lat: float, lon: float, hazards: list[Hazard]) -> list[str]:
    warnings = []
    for h in hazards:
        what = HAZARD_CATEGORIES.get(h.category)
        if what is None:
            continue
        miles = _dist(lat, lon, h.lat, h.lon)
        if miles <= HAZARD_WARNING_MILES:
            warnings.append(f"{miles:.2f} mi from {what}: {h.note}")
    return warnings


def propose(
    homes: list[Home],
    existing: list[Place],
    *,
    min_spacing_miles: float,
    hazards: list[Hazard] | None = None,
) -> list[Proposal]:
    hazards = hazards or []
    homes = sorted(homes, key=lambda h: h.student_id)
    proposals: list[Proposal] = []

    # 1. Curb-to-curb for specialized transportation.
    for h in homes:
        if h.specialized:
            proposals.append(Proposal("curb", h.lat, h.lon, [h.student_id]))
    remaining = [h for h in homes if not h.specialized]

    # 2. Reuse the nearest existing stop within walking limit.
    by_stop: dict[int, list[int]] = {}
    unplaced: list[Home] = []
    for h in remaining:
        reachable = [
            (_dist(h.lat, h.lon, p.lat, p.lon), p.id) for p in existing if _within(h, p.lat, p.lon)
        ]
        if reachable:
            by_stop.setdefault(min(reachable)[1], []).append(h.student_id)
        else:
            unplaced.append(h)
    places = {p.id: p for p in existing}
    for stop_id, ids in by_stop.items():
        p = places[stop_id]
        proposals.append(Proposal("existing", p.lat, p.lon, ids, stop_id=stop_id, label=p.label))

    # 3. Greedy grouping. neighbours[i]: homes that can walk to home i.
    neighbours = {
        a.student_id: {b.student_id for b in unplaced if _within(b, a.lat, a.lon)} for a in unplaced
    }
    by_id = {h.student_id: h for h in unplaced}
    left = set(by_id)
    new_stops: list[Proposal] = []
    while left:
        best = max(
            sorted(left),
            key=lambda i: (
                len(neighbours[i] & left),
                -sum(
                    _dist(by_id[i].lat, by_id[i].lon, by_id[j].lat, by_id[j].lon)
                    for j in neighbours[i] & left
                ),
            ),
        )
        group = sorted(neighbours[best] & left)
        median = shortest_walks([(by_id[j].lat, by_id[j].lon) for j in group])
        centre = (
            sum(by_id[j].lat for j in group) / len(group),
            sum(by_id[j].lon for j in group) / len(group),
        )
        lat, lon = next(
            (
                spot
                for spot in (median, centre)
                if all(_within(by_id[j], spot[0], spot[1]) for j in group)
            ),
            (by_id[best].lat, by_id[best].lon),
        )
        left -= set(group)

        # 4. Spacing: join a stop that's too close when everyone can walk there.
        stop = Proposal("new", lat, lon, group)
        # A new stop that's too close to another new one joins it when all
        # its students can walk there. Existing stops never need that: a
        # student within walking distance of one was already given it.
        close_new = sorted(
            (
                (other, _dist(lat, lon, other.lat, other.lon))
                for other in new_stops
                if _dist(lat, lon, other.lat, other.lon) < min_spacing_miles
            ),
            key=lambda pair: pair[1],
        )
        target = next(
            (o for o, _ in close_new if all(_within(by_id[j], o.lat, o.lon) for j in group)),
            None,
        )
        if target is not None:
            target.student_ids = sorted(target.student_ids + group)
            continue
        close_existing = [
            (place.label, _dist(lat, lon, place.lat, place.lon))
            for place in existing
            if _dist(lat, lon, place.lat, place.lon) < min_spacing_miles
        ]
        for name, miles in [
            *(("another proposed stop", m) for _, m in close_new),
            *close_existing,
        ]:
            stop.warnings.append(
                f"{miles:.2f} mi from {name} (the district's minimum spacing is "
                f"{min_spacing_miles:g} mi)"
            )
        new_stops.append(stop)
    proposals.extend(new_stops)

    numbered = (q for q in proposals if q.kind != "existing")
    for number, proposal in enumerate(numbered, start=1):
        proposal.label = (
            f"Curb stop {number}" if proposal.kind == "curb" else f"Proposed stop {number}"
        )
    for proposal in proposals:
        proposal.warnings.extend(hazard_warnings(proposal.lat, proposal.lon, hazards))
    return proposals
