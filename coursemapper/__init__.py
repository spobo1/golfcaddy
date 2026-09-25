"""coursemapper: find GPS coordinates of tee boxes and green centres for a golf course.

Data comes from OpenStreetMap, so results are only as complete as the
course's mapping there.
"""

from .mapper import build_course_map
from .models import Coordinate, CourseMap, Hole, TeeBox
from .osm import CourseNotFoundError, CourseRef, OSMClient
from .scorecard import apply_scorecard, load_scorecard

__all__ = [
    "map_course",
    "build_course_map",
    "Coordinate",
    "CourseMap",
    "CourseNotFoundError",
    "CourseRef",
    "Hole",
    "OSMClient",
    "TeeBox",
    "apply_scorecard",
    "load_scorecard",
]


def map_course(name: str, client: OSMClient | None = None) -> CourseMap:
    """Look up a golf course by name and return tee and green coordinates per hole."""
    client = client or OSMClient()
    course = client.find_course(name)
    return build_course_map(course, client.fetch_features(course))
