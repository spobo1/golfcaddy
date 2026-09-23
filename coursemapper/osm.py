"""OpenStreetMap access: Nominatim for course lookup, Overpass for features."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "golfcaddy-coursemapper/0.1 (https://github.com/spobo1/golfcaddy)"

# Overpass area ids are derived from the OSM id of the way/relation.
_AREA_OFFSET = {"way": 2_400_000_000, "relation": 3_600_000_000}

# (url, POST form data or None) -> parsed JSON
FetchJson = Callable[[str, Optional[dict]], object]


class CourseNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class CourseRef:
    name: str
    osm_type: str  # "way" or "relation"
    osm_id: int


def http_fetch_json(url: str, data: Optional[dict] = None, timeout: float = 90) -> object:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


class OSMClient:
    def __init__(
        self,
        fetch_json: FetchJson = http_fetch_json,
        nominatim_url: str = NOMINATIM_URL,
        overpass_url: str = OVERPASS_URL,
    ):
        self._fetch = fetch_json
        self._nominatim_url = nominatim_url
        self._overpass_url = overpass_url

    def find_course(self, name: str) -> CourseRef:
        """Resolve a course name to its OSM golf_course way/relation."""
        query = urllib.parse.urlencode({"q": name, "format": "jsonv2", "limit": 10})
        results = self._fetch(f"{self._nominatim_url}?{query}", None) or []
        for r in results:
            if (
                r.get("category") == "leisure"
                and r.get("type") == "golf_course"
                and r.get("osm_type") in _AREA_OFFSET
            ):
                return CourseRef(
                    name=r.get("name") or r.get("display_name") or name,
                    osm_type=r["osm_type"],
                    osm_id=int(r["osm_id"]),
                )
        raise CourseNotFoundError(f"No golf course found in OpenStreetMap for {name!r}")

    def fetch_features(self, course: CourseRef) -> list[dict]:
        """Fetch golf holes, tees and greens inside the course boundary."""
        area_id = _AREA_OFFSET[course.osm_type] + course.osm_id
        query = f"""
[out:json][timeout:60];
area({area_id})->.course;
(
  way["golf"="hole"](area.course);
  nwr["golf"="tee"](area.course);
  nwr["golf"="green"](area.course);
);
out tags geom;
"""
        result = self._fetch(self._overpass_url, {"data": query})
        return result.get("elements", [])
