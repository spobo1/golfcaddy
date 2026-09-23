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
        return _mean(pts)

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
        return _mean(pts)
    cx /= 3 * area2
    cy /= 3 * area2
    return Coordinate(lat=lat0 + cy, lon=lon0 + cx / kx)


def _mean(pts: Sequence[Coordinate]) -> Coordinate:
    return Coordinate(
        lat=sum(p.lat for p in pts) / len(pts),
        lon=sum(p.lon for p in pts) / len(pts),
    )
