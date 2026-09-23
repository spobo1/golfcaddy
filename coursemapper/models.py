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
    # "tee" when taken from a mapped tee feature, "hole_line" when inferred
    # from the start of the hole's centre line.
    source: str = "tee"


@dataclass
class Hole:
    number: Optional[int]
    tees: list[TeeBox]
    green_center: Coordinate
    par: Optional[int] = None
    handicap: Optional[int] = None
    name: Optional[str] = None
    # "green" when taken from a mapped green polygon, "hole_line" when
    # inferred from the end of the hole's centre line.
    green_source: str = "green"


@dataclass
class CourseMap:
    name: str
    osm_type: str
    osm_id: int
    holes: list[Hole] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
