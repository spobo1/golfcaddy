"""Data types returned by coursemapper."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Coordinate:
    lat: float
    lon: float


@dataclass
class TeeBox:
    location: Coordinate
    # Tee colour/name as tagged in OpenStreetMap (e.g. "blue", "red"), if any.
    name: Optional[str] = None
    # Straight-line distance from this tee box to the centre of the green.
    distance_to_green_m: Optional[float] = None
    # ...and to the front and back edges of the green, when known.
    distance_to_green_front_m: Optional[float] = None
    distance_to_green_back_m: Optional[float] = None
    # "tee" when taken from a mapped tee feature, "hole_line" when inferred
    # from the start of the hole's centre line.
    source: str = "tee"
    # Tee colours played from this box, longest first, when a scorecard was
    # applied (see coursemapper.scorecard).
    colours: list[str] = field(default_factory=list)


@dataclass
class Hazard:
    # "bunker", "water" or "lateral_water".
    kind: str
    center: Coordinate
    outline: list[Coordinate]
    # "left" or "right" of the line of play (seen from the tee), or
    # "crossing" when the hole line runs through it.
    side: str
    # Straight-line distances from the hole's back tee to the hazard's
    # nearest edge (to reach it) and farthest edge (to carry it).
    reach_from_back_tee_m: float
    carry_from_back_tee_m: float
    # From the hazard's centre to the centre of the green.
    distance_to_green_m: float


@dataclass
class Hole:
    number: Optional[int]
    tees: list[TeeBox]
    green_center: Coordinate
    par: Optional[int] = None
    handicap: Optional[int] = None
    name: Optional[str] = None
    # Length along the mapped hole line (tee to green, following doglegs).
    length_m: Optional[float] = None
    # "green" when taken from a mapped green polygon, "hole_line" when
    # inferred from the end of the hole's centre line.
    green_source: str = "green"
    # Where the line of approach enters and leaves the green. None when the
    # green's outline isn't mapped.
    green_front: Optional[Coordinate] = None
    green_back: Optional[Coordinate] = None
    # Outlines of this hole's fairway(s); some holes have split fairways.
    fairways: list[list[Coordinate]] = field(default_factory=list)
    # Bunkers and water in play on this hole, nearest to the tee first.
    hazards: list[Hazard] = field(default_factory=list)


@dataclass
class CourseMap:
    name: str
    osm_type: str
    osm_id: int
    holes: list[Hole] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
