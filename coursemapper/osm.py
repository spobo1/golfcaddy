"""OpenStreetMap access: Nominatim for course lookup, Overpass for features."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from . import osmapi
from .geo import centroid, mean_point

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "golfcaddy-coursemapper/0.1 (https://github.com/spobo1/golfcaddy)"

# OSM element types that can be a course boundary.
_AREA_TYPES = ("way", "relation")

# Errors meaning a server could not be reached (or kept failing), as opposed
# to a bad response.
NETWORK_ERRORS = (urllib.error.URLError, ConnectionError, TimeoutError)

# When the name search finds no golf course (e.g. it only matches the
# clubhouse), look for courses within this distance of the best match.
NEARBY_COURSE_RADIUS_M = 2000

# Box sizes tried, in turn, when searching near a point via the OSM API.
API_NEARBY_RADII_M = (500, 1000, NEARBY_COURSE_RADIUS_M)

_RETRY_STATUS = {429, 502, 503, 504}
_RETRY_DELAYS_S = (2, 4, 8)

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
    """Fetch JSON, retrying on rate limits, server overload and dropped connections."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    for attempt, delay in enumerate((*_RETRY_DELAYS_S, None)):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if delay is None or e.code not in _RETRY_STATUS:
                raise
            retry_after = e.headers.get("Retry-After", "")
            delay = int(retry_after) if retry_after.isdigit() else delay
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if delay is None:
                raise
        time.sleep(delay)


class OSMClient:
    def __init__(
        self,
        fetch_json: FetchJson = http_fetch_json,
        nominatim_url: str = NOMINATIM_URL,
        overpass_url: str = OVERPASS_URL,
        api_url: str = osmapi.API_URL,
    ):
        self._fetch = fetch_json
        self._nominatim_url = nominatim_url
        self._overpass_url = overpass_url
        self._api_url = api_url

    def find_course(self, name: str) -> CourseRef:
        """Resolve a course name to its OSM golf_course way/relation."""
        query = urllib.parse.urlencode({"q": name, "format": "jsonv2", "limit": 10})
        results = self._fetch(f"{self._nominatim_url}?{query}", None) or []
        for r in results:
            if (
                r.get("category") == "leisure"
                and r.get("type") == "golf_course"
                and r.get("osm_type") in _AREA_TYPES
            ):
                return CourseRef(
                    name=r.get("name") or r.get("display_name") or name,
                    osm_type=r["osm_type"],
                    osm_id=int(r["osm_id"]),
                )
        if results and "lat" in results[0]:
            course = self._find_course_near(name, float(results[0]["lat"]), float(results[0]["lon"]))
            if course is not None:
                return course
        raise CourseNotFoundError(f"No golf course found in OpenStreetMap for {name!r}")

    def _find_course_near(self, name: str, lat: float, lon: float) -> Optional[CourseRef]:
        """Pick the golf course near a point, preferring one whose name matches."""
        query = f"""
[out:json][timeout:60];
(
  way["leisure"="golf_course"](around:{NEARBY_COURSE_RADIUS_M},{lat},{lon});
  relation["leisure"="golf_course"](around:{NEARBY_COURSE_RADIUS_M},{lat},{lon});
);
out tags center;
"""
        try:
            elements = self._overpass(query)
        except NETWORK_ERRORS:
            elements = self._api_courses_near(lat, lon)
        if not elements:
            return None
        wanted = _name_words(name)

        def rank(el: dict) -> tuple:
            common = wanted & _name_words(el.get("tags", {}).get("name", ""))
            center = el.get("center", {})
            dist2 = (center.get("lat", lat) - lat) ** 2 + (center.get("lon", lon) - lon) ** 2
            # Most shared distinctive words first, then nearest.
            return (-len(common), dist2)

        best = min(elements, key=rank)
        return CourseRef(
            name=best.get("tags", {}).get("name") or name,
            osm_type=best["type"],
            osm_id=int(best["id"]),
        )

    def fetch_features(self, course: CourseRef) -> list[dict]:
        """Fetch golf holes, tees, greens, fairways, bunkers and water inside the course boundary."""
        # map_to_area builds the area from the boundary itself; Overpass's
        # precomputed area ids (2400000000 + way id) can be missing.
        query = f"""
[out:json][timeout:60];
{course.osm_type}({course.osm_id});
map_to_area->.course;
(
  way["golf"="hole"](area.course);
  nwr["golf"="tee"](area.course);
  nwr["golf"="green"](area.course);
  nwr["golf"~"^(bunker|water_hazard|lateral_water_hazard|fairway)$"](area.course);
  nwr["natural"="water"](area.course);
);
out tags geom;
"""
        try:
            elements = self._overpass(query)
        except NETWORK_ERRORS:
            return self._api_features(course)
        if not any(e.get("tags", {}).get("golf") == "hole" for e in elements):
            # Overpass answered but found no holes; check the main API before
            # concluding the course has none mapped.
            return self._api_features(course)
        return elements

    def _overpass(self, query: str) -> list[dict]:
        return self._fetch(self._overpass_url, {"data": query}).get("elements", [])

    def _api_map(self, box: tuple[float, float, float, float]) -> list[dict]:
        bbox_param = ",".join(f"{v:.7f}" for v in box)
        result = self._fetch(f"{self._api_url}/map.json?bbox={bbox_param}", None)
        return osmapi.attach_geometry(result.get("elements", []))

    def _api_features(self, course: CourseRef) -> list[dict]:
        """Fallback for fetch_features using the main OSM API."""
        full = self._fetch(f"{self._api_url}/{course.osm_type}/{course.osm_id}/full.json", None)
        elements = osmapi.attach_geometry(full.get("elements", []))
        boundary = next(e for e in elements if e["type"] == course.osm_type and e["id"] == course.osm_id)
        rings = osmapi.boundary_rings(boundary)
        box = osmapi.bbox((p for ring in rings for p in ring), pad=osmapi.BBOX_PADDING_DEG)
        return osmapi.golf_features_inside(self._api_map(box), rings)

    def _api_courses_near(self, lat: float, lon: float) -> list[dict]:
        """Fallback for _find_course_near: golf courses around a point, with centres.

        The API caps how many nodes one request returns, so start with a small
        box (a clubhouse is usually beside its course) and widen it only while
        nothing is found and the API accepts the size.
        """
        for radius_m in API_NEARBY_RADII_M:
            pad = radius_m / 111_000
            try:
                elements = self._api_map((lon - pad, lat - pad, lon + pad, lat + pad))
            except urllib.error.HTTPError as e:
                if e.code == 400:  # too many nodes in the box
                    break
                raise
            courses = []
            for e in elements:
                if e["type"] in _AREA_TYPES and e.get("tags", {}).get("leisure") == "golf_course":
                    points = osmapi.element_points(e, roles={"outer"})
                    if points:
                        # Relation member ways are not joined into rings, so average them.
                        c = centroid(points) if e["type"] == "way" else mean_point(points)
                        courses.append(dict(e, center={"lat": c.lat, "lon": c.lon}))
            if courses:
                return courses
        return []


# Words too common in course names to tell courses apart.
_GENERIC_NAME_WORDS = {"golf", "links", "course", "club", "country", "the", "gc", "cc", "and", "&", "of"}


def _name_words(name: str) -> set[str]:
    words = re.findall(r"[\w&]+", name.lower())
    return {w for w in words if w not in _GENERIC_NAME_WORDS}
