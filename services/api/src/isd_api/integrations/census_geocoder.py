"""US Census Bureau geocoder (spec section 3's student addresses; chosen by
the product owner on 2026-09-28): free, no API key, US addresses only.

https://geocoding.geo.census.gov/geocoder/ — the "onelineaddress" lookup
against the current public address ranges. Only the address is sent (no
name, no student id), over HTTPS. Nothing is logged here, since the
address is personal data.

When there's no match, callers fall back to a pin placed by hand on the
map (`GeocodeSource.MANUAL`), so an address the Census doesn't know (a
new subdivision, a rural route) still works.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

ENDPOINT = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
BENCHMARK = "Public_AR_Current"
TIMEOUT_SECONDS = 10


class GeocoderUnavailable(Exception):
    """The Census service couldn't be reached or answered with an error."""


@dataclass(frozen=True)
class GeocodeMatch:
    lat: float
    lon: float
    matched_address: str


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        raise GeocoderUnavailable(str(err)) from None


def parse(payload: dict) -> GeocodeMatch | None:
    """The best match from a Census response, or None when there's none."""
    matches = (payload.get("result") or {}).get("addressMatches") or []
    if not matches:
        return None
    best = matches[0]
    coordinates = best.get("coordinates") or {}
    try:
        lon, lat = float(coordinates["x"]), float(coordinates["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return GeocodeMatch(lat=lat, lon=lon, matched_address=str(best.get("matchedAddress", ""))[:500])


def geocode(address: str) -> GeocodeMatch | None:
    query = urllib.parse.urlencode({"address": address, "benchmark": BENCHMARK, "format": "json"})
    return parse(_fetch_json(f"{ENDPOINT}?{query}"))
