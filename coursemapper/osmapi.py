"""Fallback data source: the main OpenStreetMap editing API.

Used only when Overpass cannot be reached. The API returns raw
nodes/ways/relations for a bounding box, so we attach geometry ourselves to
match Overpass's ``out geom`` shape and do the "inside the course" filtering
locally. Per the OSM API usage policy this is for occasional, low-volume use.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .geo import point_in_rings
from .models import Coordinate

API_URL = "https://api.openstreetmap.org/api/0.6"

# Padding added around the course boundary when downloading features, so
# holes drawn slightly outside the boundary are still included.
BBOX_PADDING_DEG = 0.001


def attach_geometry(elements: list[dict]) -> list[dict]:
    """Give ways a ``geometry`` list and relation members theirs, like Overpass."""
    nodes = {e["id"]: e for e in elements if e["type"] == "node"}
    ways = {}
    for e in elements:
        if e["type"] == "way":
            geometry = [
                {"lat": nodes[n]["lat"], "lon": nodes[n]["lon"]} for n in e.get("nodes", []) if n in nodes
            ]
            ways[e["id"]] = dict(e, geometry=geometry)
    out = []
    for e in elements:
        if e["type"] == "node":
            out.append(e)
        elif e["type"] == "way":
            out.append(ways[e["id"]])
        else:
            members = [
                dict(m, geometry=ways[m["ref"]]["geometry"])
                for m in e.get("members", [])
                if m.get("type") == "way" and m.get("ref") in ways
            ]
            out.append(dict(e, members=members))
    return out


def element_points(el: dict, roles: Optional[set] = None) -> list[Coordinate]:
    """All coordinates of an element with attached geometry."""
    if el["type"] == "node":
        return [Coordinate(el["lat"], el["lon"])]
    if el["type"] == "way":
        return [Coordinate(p["lat"], p["lon"]) for p in el.get("geometry", [])]
    return [
        Coordinate(p["lat"], p["lon"])
        for m in el.get("members", [])
        if roles is None or m.get("role") in roles
        for p in m.get("geometry", [])
    ]


def boundary_rings(el: dict) -> list[list[Coordinate]]:
    """The rings (as point lists) making up a way or multipolygon's outline."""
    if el["type"] == "way":
        return [element_points(el)]
    return [
        [Coordinate(p["lat"], p["lon"]) for p in m["geometry"]]
        for m in el.get("members", [])
        if m.get("role") in ("outer", "inner") and m.get("geometry")
    ]


def bbox(points: Iterable[Coordinate], pad: float = 0.0) -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat), the order the OSM API expects."""
    pts = list(points)
    return (
        min(p.lon for p in pts) - pad,
        min(p.lat for p in pts) - pad,
        max(p.lon for p in pts) + pad,
        max(p.lat for p in pts) + pad,
    )


def golf_features_inside(elements: list[dict], rings: list[list[Coordinate]]) -> list[dict]:
    """Holes, tees and greens with at least one point inside the course.

    Mirrors Overpass's ``(area)`` filter, which matches a way when any of its
    nodes falls inside the area.
    """
    return [
        e
        for e in elements
        if (e.get("tags", {}).get("golf") in ("tee", "green") or _is_hole(e))
        and any(point_in_rings(p, rings) for p in element_points(e))
    ]


def _is_hole(el: dict) -> bool:
    return el["type"] == "way" and el.get("tags", {}).get("golf") == "hole"
