"""Label mapped tee boxes with tee colours from a course scorecard.

OpenStreetMap rarely records which tee box is which colour, but a scorecard
gives each colour's yardage per hole. The longest set is taken to play from
the rearmost mapped box; every other colour goes on the box whose distance
forward of that box best matches how much shorter the colour plays. Working
from differences keeps doglegs and the scorecard's along-the-fairway
measuring from skewing the match.
"""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from .models import CourseMap

YARDS_PER_METRE = 1.0936133


def load_scorecard(path: str) -> dict[str, list[float]]:
    """Read a scorecard JSON file (see scorecards/) as colour -> yardages in metres."""
    with open(path) as f:
        data = json.load(f)
    per_metre = YARDS_PER_METRE if data.get("unit", "yd") == "yd" else 1.0
    return {colour: [y / per_metre for y in yards] for colour, yards in data["tees"].items()}


def apply_scorecard(course: CourseMap, tees: Mapping[str, Sequence[float]]) -> None:
    """Set ``colours`` on each hole's tee boxes.

    ``tees`` maps a colour to its length in metres for each hole, in hole
    order (index 0 is hole 1). Holes without a number or without a
    scorecard entry are left alone.
    """
    for hole in course.holes:
        if hole.number is None or not hole.tees:
            continue
        lengths = {c: ys[hole.number - 1] for c, ys in tees.items() if len(ys) >= hole.number}
        if not lengths:
            continue
        longest = max(lengths.values())
        back = hole.tees[0].distance_to_green_m or 0.0
        # How far forward of the back box each mapped box sits.
        forward = [back - (t.distance_to_green_m or 0.0) for t in hole.tees]
        for tee in hole.tees:
            tee.colours = []
        for colour, length in sorted(lengths.items(), key=lambda kv: -kv[1]):
            shorter_by = longest - length
            best = min(range(len(hole.tees)), key=lambda i: abs(forward[i] - shorter_by))
            hole.tees[best].colours.append(colour)
