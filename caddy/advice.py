"""Pick a club for the shot in front of the player.

Combines a hole from coursemapper (green front/centre/back and hazards) with
the player's club distances from clubtracker. Distances in the advice are in
yards.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

from clubtracker import ClubDistance, ClubTracker, normalize_club
from coursemapper.geo import LocalProjection, distance_m
from coursemapper.models import Coordinate, Hazard, Hole

YARDS_PER_METRE = 1.0936133

# A hazard whose edge comes within this of the line to the green is in the way.
IN_THE_WAY_YD = 10.0
# Hazards further than this to the side aren't worth mentioning.
NEARBY_YD = 30.0
# Hazards more than this beyond the back of the green are ignored.
BEYOND_GREEN_YD = 30.0
# Leeway around a hazard when deciding whether a club lands or stops in it,
# since nobody hits every shot their average distance.
SAFETY_YD = 5.0


@dataclass
class HazardAhead:
    kind: str  # "bunker", "water" or "lateral_water"
    # "crossing" when it's in the way, otherwise "left" or "right" of the
    # line to the green, as seen from the player.
    side: str
    # Along the line to the green, from the player: where it starts and ends.
    reach_yd: float
    carry_yd: float

    @property
    def in_the_way(self) -> bool:
        return self.side == "crossing"


@dataclass
class ShotAdvice:
    club: str
    distance: ClubDistance
    to_center_yd: float
    to_front_yd: Optional[float]
    to_back_yd: Optional[float]
    # "target": the club closest to the green centre. "carry": more club to
    # clear a hazard. "front": less club, to the front of the green, to stay
    # short of a hazard further on. "layup": less club, to stop short of a
    # hazard before the green. "no_safe_club": every club risks a hazard, so
    # this is the club closest to the target.
    plan: str
    reason: str
    # Hazards along or beside the line to the green, nearest first.
    hazards: list[HazardAhead] = field(default_factory=list)


def tee_position(hole: Hole, colour: Optional[str] = None) -> Coordinate:
    """The tee box a colour plays from (see coursemapper's scorecard), or the back tee."""
    if colour is not None:
        for tee in hole.tees:
            if any(c.lower() == colour.lower() for c in tee.colours):
                return tee.location
    return hole.tees[0].location


def hazards_ahead(hole: Hole, position: Coordinate) -> list[HazardAhead]:
    """The hole's hazards along or beside the line from ``position`` to the green centre."""
    proj = LocalProjection(position)
    gx, gy = proj.xy(hole.green_center)
    length = math.hypot(gx, gy)
    if length == 0:
        return []
    ux, uy = gx / length, gy / length
    back = distance_m(position, hole.green_back) if hole.green_back else length
    limit = back + BEYOND_GREEN_YD / YARDS_PER_METRE

    result = []
    for hazard in hole.hazards:
        pts = [proj.xy(p) for p in hazard.outline]
        along = [x * ux + y * uy for x, y in pts]
        # Positive offsets are left of the line.
        offset = [ux * y - uy * x for x, y in pts]
        # Where the hazard sits on the line itself: where its edges cross the
        # line, plus any corners close enough to it.
        on_line = [t for t, o in zip(along, offset) if abs(o) * YARDS_PER_METRE <= IN_THE_WAY_YD]
        ring = list(zip(along, offset))
        for (t1, o1), (t2, o2) in zip(ring, ring[1:] + ring[:1]):
            if (o1 > 0) != (o2 > 0):
                on_line.append(t1 + (t2 - t1) * o1 / (o1 - o2))
        ahead = [t for t in on_line if 0 <= t <= limit]
        if ahead:
            result.append(_ahead(hazard, "crossing", min(ahead), max(ahead)))
            continue
        near = [
            (t, o) for t, o in zip(along, offset) if 0 <= t <= limit and abs(o) * YARDS_PER_METRE <= NEARBY_YD
        ]
        if near:
            side = "left" if sum(o for _, o in near) > 0 else "right"
            result.append(_ahead(hazard, side, min(t for t, _ in near), max(t for t, _ in near)))
    return sorted(result, key=lambda h: h.reach_yd)


def advise_shot(
    tracker: ClubTracker,
    user_id: str,
    hole: Hole,
    position: Coordinate,
    clubs: Optional[Iterable[str]] = None,
    include_driver: Optional[bool] = None,
) -> ShotAdvice:
    """Suggest a club from ``position`` to the green, steering clear of hazards in the way.

    Of the clubs that won't land or stop in a hazard in the way, picks the
    one finishing closest to the green centre (counting yards past the back
    of the green double), so it takes more club to carry a hazard where that
    works, or lays up short of it where it doesn't.
    ``clubs`` limits the choice to the player's bag. The driver is only
    considered when the green is out of reach of every other club, unless
    ``include_driver`` says otherwise.
    """
    to_center = distance_m(position, hole.green_center) * YARDS_PER_METRE
    to_front = distance_m(position, hole.green_front) * YARDS_PER_METRE if hole.green_front else None
    to_back = distance_m(position, hole.green_back) * YARDS_PER_METRE if hole.green_back else None
    ahead = hazards_ahead(hole, position)
    in_the_way = [h for h in ahead if h.in_the_way]

    allowed = {normalize_club(c) for c in clubs} if clubs is not None else None
    options = [d for d in tracker.bag(user_id) if allowed is None or d.club in allowed]
    others = [d for d in options if d.club != "driver"]
    if include_driver is None:
        include_driver = not others or max(d.total_yd for d in others) < to_center
    if not include_driver:
        options = others
    if not options:
        raise ValueError("No clubs to choose from")
    # Longest first, so ties go to the longer club.
    options.sort(key=lambda d: -d.total_yd)

    def closest(candidates: list[ClubDistance]) -> ClubDistance:
        # Finishing over the back of the green usually brings its own
        # trouble, so each yard past the back counts double.
        def miss(d: ClubDistance) -> float:
            over_back = max(0.0, d.total_yd - to_back) if to_back is not None else 0.0
            return abs(d.total_yd - to_center) + over_back

        return min(candidates, key=miss)

    best = closest(options)
    safe = [d for d in options if not any(_ends_up_in(d, h) for h in in_the_way)]
    if not safe:
        chosen, plan = best, "no_safe_club"
    else:
        chosen = closest(safe)
        plan = "target" if chosen is best else "carry" if chosen.total_yd > best.total_yd else "layup"
        if plan == "layup" and to_front is not None and chosen.total_yd >= to_front - SAFETY_YD:
            plan = "front"

    return ShotAdvice(
        club=chosen.club,
        distance=chosen,
        to_center_yd=round(to_center, 1),
        to_front_yd=_round(to_front),
        to_back_yd=_round(to_back),
        plan=plan,
        reason=_reason(chosen, best, plan, to_center, to_front, [h for h in in_the_way if _ends_up_in(best, h)]),
        hazards=ahead,
    )


def _ends_up_in(club: ClubDistance, hazard: HazardAhead) -> bool:
    """Whether the ball would land in the hazard, or roll into it and stop there."""
    return club.carry_yd <= hazard.carry_yd + SAFETY_YD and club.total_yd >= hazard.reach_yd - SAFETY_YD


def _reason(chosen, best, plan, to_center, to_front, blocking) -> str:
    name = _NAMES.get(chosen.club, chosen.club)
    hazard = blocking[0] if blocking else None
    what = f"the {_KIND[hazard.kind]}" if hazard else ""
    if plan == "carry":
        return f"Take {name} to carry {what} ({hazard.carry_yd:.0f} to carry, {name} carries {chosen.carry_yd:.0f})."
    if plan == "front":
        return f"Play {name} to the front of the green, staying short of {what} ({hazard.reach_yd:.0f} to reach)."
    if plan == "layup":
        return f"Lay up with {name}, about {hazard.reach_yd - chosen.total_yd:.0f} short of {what} ({hazard.reach_yd:.0f} to reach)."
    if plan == "no_safe_club":
        return f"Every club risks {what}; {name} finishes closest to the green."
    miss = chosen.total_yd - to_center
    if to_front is not None and chosen.total_yd < to_front:
        return f"The green is out of reach; {name} leaves about {to_center - chosen.total_yd:.0f} to the centre."
    if abs(miss) < 1:
        return f"{name.capitalize()} finishes at the centre of the green."
    return f"{name.capitalize()} finishes about {abs(miss):.0f} {'long' if miss > 0 else 'short'} of the centre."


_KIND = {"bunker": "bunker", "water": "water", "lateral_water": "water"}
_NAMES = {"driver": "driver", "pw": "pitching wedge", "gw": "gap wedge", "sw": "sand wedge", "lw": "lob wedge"}
for _n in range(3, 10):
    _NAMES[f"{_n}i"] = f"{_n} iron"
for _n in (3, 5, 7):
    _NAMES[f"{_n}w"] = f"{_n} wood"
for _n in (3, 4, 5):
    _NAMES[f"{_n}h"] = f"{_n} hybrid"


def _ahead(hazard: Hazard, side: str, reach_m: float, carry_m: float) -> HazardAhead:
    return HazardAhead(hazard.kind, side, round(reach_m * YARDS_PER_METRE, 1), round(carry_m * YARDS_PER_METRE, 1))


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 1)
