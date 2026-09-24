"""Turn raw OpenStreetMap golf features into per-hole tees, greens and hazards.

OpenStreetMap convention (https://wiki.openstreetmap.org/wiki/Tag:golf=hole):
each hole is a way tagged ``golf=hole`` drawn from the tee to the green, with
``ref`` holding the hole number. Tee boxes (``golf=tee``) and greens
(``golf=green``) are mapped as separate areas or points. We match each tee to
the hole whose line starts nearest to it and each hole to the green nearest
its line's end, falling back to the line's endpoints when nothing is mapped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .geo import centroid, distance_m
from .hazards import extract_hazards, hazards_for_holes
from .models import Coordinate, CourseMap, Hole, TeeBox
from .osm import CourseRef

# How far a mapped feature may be from a hole line's endpoint and still be
# considered part of that hole.
TEE_MATCH_RADIUS_M = 150.0
GREEN_MATCH_RADIUS_M = 75.0

# A tee more than this beyond the hole line's length from the green is
# assumed to belong to another nearby hole if one fits better.
TEE_OVERHANG_M = 25.0


@dataclass
class _Feature:
    osm_key: str
    tags: dict
    center: Coordinate


@dataclass
class _HoleLine:
    tags: dict
    start: Coordinate
    end: Coordinate
    length_m: float
    points: list[Coordinate]


def build_course_map(course: CourseRef, elements: list[dict]) -> CourseMap:
    hole_lines: list[_HoleLine] = []
    tees: list[_Feature] = []
    greens: list[_Feature] = []

    for el in elements:
        kind = el.get("tags", {}).get("golf")
        if kind == "hole":
            pts = _points(el)
            if len(pts) >= 2:
                length = sum(distance_m(a, b) for a, b in zip(pts, pts[1:]))
                hole_lines.append(_HoleLine(el["tags"], pts[0], pts[-1], length, pts))
        elif kind in ("tee", "green"):
            pts = _points(el)
            if pts:
                feature = _Feature(f"{el['type']}/{el['id']}", el.get("tags", {}), centroid(pts))
                (tees if kind == "tee" else greens).append(feature)

    tees_by_hole = _assign_tees(hole_lines, tees)
    green_by_hole = _assign_greens(hole_lines, greens)

    holes = []
    for i, line in enumerate(hole_lines):
        green = green_by_hole.get(i)
        green_center = green if green is not None else line.end
        tee_boxes = [
            TeeBox(location=t.center, name=_tee_name(t.tags)) for t in tees_by_hole.get(i, [])
        ] or [TeeBox(location=line.start, source="hole_line")]
        for tee in tee_boxes:
            tee.distance_to_green_m = round(distance_m(tee.location, green_center), 1)
        # Longest (back) tees first.
        tee_boxes.sort(key=lambda t: -(t.distance_to_green_m or 0))
        holes.append(
            Hole(
                number=_int(line.tags.get("ref")),
                tees=tee_boxes,
                green_center=green_center,
                par=_int(line.tags.get("par")),
                handicap=_int(line.tags.get("handicap")),
                name=line.tags.get("name"),
                length_m=round(line.length_m, 1),
                green_source="green" if green is not None else "hole_line",
            )
        )

    hazards = hazards_for_holes(
        [line.points for line in hole_lines],
        [hole.tees[0].location for hole in holes],
        [hole.green_center for hole in holes],
        extract_hazards(elements, _points),
    )
    for i, hole in enumerate(holes):
        hole.hazards = hazards.get(i, [])

    holes.sort(key=lambda h: (h.number is None, h.number or 0))
    return CourseMap(name=course.name, osm_type=course.osm_type, osm_id=course.osm_id, holes=holes)


def _assign_tees(lines: list[_HoleLine], tees: list[_Feature]) -> dict[int, list[_Feature]]:
    """Give each tee box to the hole whose line starts closest to it.

    A tee tagged with a hole number (``ref``) goes to the nearest hole with
    that number. Hole lines are usually drawn from the back tee, so a tee
    farther from the green than the hole is long more likely belongs to
    another nearby hole; it only stays with the nearest hole when no other
    hole fits (some courses draw lines from a middle tee).
    """
    result: dict[int, list[_Feature]] = {}
    for tee in tees:
        candidates = sorted(
            (i for i, line in enumerate(lines) if distance_m(tee.center, line.start) <= TEE_MATCH_RADIUS_M),
            key=lambda i: distance_m(tee.center, lines[i].start),
        )
        ref = _int(tee.tags.get("ref"))
        numbered = [i for i in candidates if _int(lines[i].tags.get("ref")) == ref]
        candidates = numbered or candidates
        plausible = [
            i for i in candidates if distance_m(tee.center, lines[i].end) <= lines[i].length_m + TEE_OVERHANG_M
        ]
        if plausible or candidates:
            result.setdefault((plausible or candidates)[0], []).append(tee)
    return result


def _assign_greens(lines: list[_HoleLine], greens: list[_Feature]) -> dict[int, Coordinate]:
    """Find each hole's green centre.

    A green shared by several holes (a double green) has a centroid that is
    not the centre of any one hole's target, so for those we use each hole
    line's end point, which mappers place on that hole's half of the green.
    """
    chosen: dict[int, _Feature] = {}
    for i, line in enumerate(lines):
        best = _nearest(line.end, [g.center for g in greens], GREEN_MATCH_RADIUS_M)
        if best is not None:
            chosen[i] = greens[best]

    users: dict[str, int] = {}
    for green in chosen.values():
        users[green.osm_key] = users.get(green.osm_key, 0) + 1
    return {
        i: (lines[i].end if users[green.osm_key] > 1 else green.center)
        for i, green in chosen.items()
    }


def _nearest(target: Coordinate, candidates: list[Coordinate], max_m: float) -> Optional[int]:
    best, best_d = None, max_m
    for i, c in enumerate(candidates):
        d = distance_m(target, c)
        if d <= best_d:
            best, best_d = i, d
    return best


def _points(el: dict) -> list[Coordinate]:
    if el["type"] == "node":
        return [Coordinate(el["lat"], el["lon"])]
    if el["type"] == "way":
        return [Coordinate(p["lat"], p["lon"]) for p in el.get("geometry", [])]
    # Multipolygon relation: use its (first) outer ring.
    for member in el.get("members", []):
        if member.get("role") == "outer" and member.get("geometry"):
            return [Coordinate(p["lat"], p["lon"]) for p in member["geometry"]]
    return []


def _tee_name(tags: dict) -> Optional[str]:
    return tags.get("tee") or tags.get("name") or tags.get("colour")


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
