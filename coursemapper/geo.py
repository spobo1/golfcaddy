"""Small geodesy helpers (no external dependencies)."""

from __future__ import annotations

import math
from typing import Sequence

from .models import Coordinate

EARTH_RADIUS_M = 6_371_008.8


def distance_m(a: Coordinate, b: Coordinate) -> float:
    """Great-circle (haversine) distance in metres."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dphi = phi2 - phi1
    dlmb = math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def centroid(points: Sequence[Coordinate]) -> Coordinate:
    """Centroid of a polygon ring (or mean of points if degenerate).

    Uses an area-weighted centroid on a local equirectangular projection,
    which is accurate for features the size of a green or tee box.
    """
    if not points:
        raise ValueError("centroid of empty point list")
    pts = list(points)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return mean_point(pts)

    lat0 = sum(p.lat for p in pts) / len(pts)
    lon0 = sum(p.lon for p in pts) / len(pts)
    kx = math.cos(math.radians(lat0))
    xy = [((p.lon - lon0) * kx, p.lat - lat0) for p in pts]

    area2 = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        cross = x1 * y2 - x2 * y1
        area2 += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area2) < 1e-18:
        return mean_point(pts)
    cx /= 3 * area2
    cy /= 3 * area2
    return Coordinate(lat=lat0 + cy, lon=lon0 + cx / kx)


def mean_point(pts: Sequence[Coordinate]) -> Coordinate:
    """Average of the points."""
    return Coordinate(
        lat=sum(p.lat for p in pts) / len(pts),
        lon=sum(p.lon for p in pts) / len(pts),
    )


def point_in_rings(point: Coordinate, rings: Sequence[Sequence[Coordinate]]) -> bool:
    """Even-odd point-in-polygon test over a set of rings.

    Works for multipolygons (inner rings cut holes) and does not require the
    outer ring's member ways to be joined in order, because only the
    parity of edge crossings matters.
    """
    inside = False
    for ring in rings:
        for a, b in zip(ring, ring[1:]):
            if (a.lat > point.lat) != (b.lat > point.lat):
                lon_at = a.lon + (point.lat - a.lat) * (b.lon - a.lon) / (b.lat - a.lat)
                if point.lon < lon_at:
                    inside = not inside
    return inside


class LocalProjection:
    """Flat x/y metres around an origin (x east, y north).

    Accurate to well under a metre across a golf course.
    """

    def __init__(self, origin: Coordinate):
        self._lat0, self._lon0 = origin.lat, origin.lon
        self._ky = math.radians(EARTH_RADIUS_M)
        self._kx = self._ky * math.cos(math.radians(origin.lat))

    def xy(self, c: Coordinate) -> tuple[float, float]:
        return ((c.lon - self._lon0) * self._kx, (c.lat - self._lat0) * self._ky)

    def coord(self, p: tuple[float, float]) -> Coordinate:
        return Coordinate(lat=self._lat0 + p[1] / self._ky, lon=self._lon0 + p[0] / self._kx)


XY = tuple[float, float]


def offset_from_polyline(p: XY, line: Sequence[XY]) -> float:
    """Signed distance from a point to a polyline: positive left, negative right.

    Left and right are as seen travelling along the line from its start.
    """
    best, best_abs = 0.0, math.inf
    for a, b in zip(line, line[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / seg2))
        qx, qy = a[0] + t * dx, a[1] + t * dy
        d = math.hypot(p[0] - qx, p[1] - qy)
        if d < best_abs:
            cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0])
            best, best_abs = (d if cross >= 0 else -d), d
    return best


def segments_intersect(a: XY, b: XY, c: XY, d: XY) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return (orient(a, b, c) > 0) != (orient(a, b, d) > 0) and (orient(c, d, a) > 0) != (orient(c, d, b) > 0)


def point_back_along(line: Sequence[XY], distance: float) -> XY:
    """The point ``distance`` back from the end of a polyline (or its start)."""
    remaining = distance
    for a, b in zip(reversed(line[1:]), reversed(line[:-1])):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg >= remaining and seg > 0:
            t = remaining / seg
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        remaining -= seg
    return line[0]


def chord_through(ring: Sequence[XY], approach: XY, center: XY) -> "tuple[XY, XY] | None":
    """Where the line from ``approach`` through ``center`` crosses a polygon's edge.

    Returns (front, back): the last crossing before the centre and the first
    one after it. None if the centre is not inside the polygon.
    """
    dx, dy = center[0] - approach[0], center[1] - approach[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return None
    ux, uy = dx / length, dy / length
    hits = []
    for a, b in zip(ring, ring[1:]):
        ex, ey = b[0] - a[0], b[1] - a[1]
        denom = ux * ey - uy * ex
        if denom == 0:
            continue
        # Solve approach + t*u = a + s*e for t (along the approach) and s (along the edge).
        wx, wy = a[0] - approach[0], a[1] - approach[1]
        t = (wx * ey - wy * ex) / denom
        s = (wx * uy - wy * ux) / denom
        if 0 <= s <= 1:
            hits.append(t)
    before = [t for t in hits if t <= length]
    after = [t for t in hits if t >= length]
    if not before or not after:
        return None
    tf, tb = max(before), min(after)
    return (approach[0] + tf * ux, approach[1] + tf * uy), (approach[0] + tb * ux, approach[1] + tb * uy)
