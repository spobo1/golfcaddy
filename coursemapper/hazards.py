"""Bunkers and water hazards, matched to the holes they are in play on.

OpenStreetMap does not link hazards to holes, so we measure how close each
hazard's outline comes to each hole's line of play. A bunker goes to the
nearest hole; a pond or stream can be in play on several holes, so water goes
to every hole that passes close enough.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .geo import LocalProjection, centroid, distance_m, offset_from_polyline, point_in_rings, segments_intersect
from .models import Coordinate, Hazard

# How close a hole's line must come to a hazard's edge for it to count.
BUNKER_MATCH_M = 50.0
WATER_MATCH_M = 50.0

_GOLF_KINDS = {"bunker": "bunker", "water_hazard": "water", "lateral_water_hazard": "lateral_water"}


@dataclass
class HazardFeature:
    kind: str
    outline: list[Coordinate]
    center: Coordinate


def extract_hazards(elements: list[dict], points: Callable[[dict], list[Coordinate]]) -> list[HazardFeature]:
    """Bunkers and water from raw elements.

    Plain ``natural=water`` is included unless it duplicates a mapped golf
    water hazard (the same pond drawn twice), which is common.
    """
    golf, plain_water = [], []
    for el in elements:
        tags = el.get("tags", {})
        kind = _GOLF_KINDS.get(tags.get("golf"))
        if kind is None and tags.get("natural") == "water":
            kind = "plain_water"
        if kind is None:
            continue
        outline = points(el)
        if not outline:
            continue
        feature = HazardFeature(kind, outline, centroid(outline))
        (plain_water if kind == "plain_water" else golf).append(feature)

    golf_water = [f for f in golf if f.kind != "bunker"]
    for water in plain_water:
        if not any(_overlaps(water, g) for g in golf_water):
            golf.append(HazardFeature("water", water.outline, water.center))
    return golf


def hazards_for_holes(
    lines: Sequence[Sequence[Coordinate]],
    back_tees: Sequence[Coordinate],
    greens: Sequence[Coordinate],
    features: list[HazardFeature],
) -> dict[int, list[Hazard]]:
    """Map hole index -> hazards in play, nearest to the back tee first."""
    if not lines:
        return {}
    proj = LocalProjection(lines[0][0])
    lines_xy = [[proj.xy(p) for p in line] for line in lines]

    result: dict[int, list[Hazard]] = {}
    for feature in features:
        outline_xy = [proj.xy(p) for p in feature.outline]
        gaps = [_gap(feature, outline_xy, line, line_xy) for line, line_xy in zip(lines, lines_xy)]
        if feature.kind == "bunker":
            best = min(range(len(lines)), key=lambda i: gaps[i][0])
            chosen = [best] if gaps[best][0] <= BUNKER_MATCH_M else []
        else:
            chosen = [i for i, (gap, _) in enumerate(gaps) if gap <= WATER_MATCH_M]

        for i in chosen:
            crosses = gaps[i][1]
            if crosses:
                side = "crossing"
            else:
                side = "left" if offset_from_polyline(proj.xy(feature.center), lines_xy[i]) > 0 else "right"
            edge = [distance_m(back_tees[i], p) for p in feature.outline]
            result.setdefault(i, []).append(
                Hazard(
                    kind=feature.kind,
                    center=feature.center,
                    outline=feature.outline,
                    side=side,
                    reach_from_back_tee_m=round(min(edge), 1),
                    carry_from_back_tee_m=round(max(edge), 1),
                    distance_to_green_m=round(distance_m(feature.center, greens[i]), 1),
                )
            )
    for hazards in result.values():
        hazards.sort(key=lambda h: h.reach_from_back_tee_m)
    return result


def _gap(feature: HazardFeature, outline_xy, line: Sequence[Coordinate], line_xy) -> tuple[float, bool]:
    """(closest distance from the hole line to the hazard edge, whether it crosses)."""
    if len(outline_xy) >= 3:
        edges = list(zip(outline_xy, outline_xy[1:]))
        crosses = any(point_in_rings(p, [feature.outline]) for p in line) or any(
            segments_intersect(a, b, c, d) for a, b in zip(line_xy, line_xy[1:]) for c, d in edges
        )
        if crosses:
            return 0.0, True
    return min(abs(offset_from_polyline(p, line_xy)) for p in outline_xy), False


def _overlaps(a: HazardFeature, b: HazardFeature) -> bool:
    return point_in_rings(a.center, [b.outline]) or point_in_rings(b.center, [a.outline])
