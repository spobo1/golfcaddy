import unittest

from coursemapper import (
    Coordinate,
    CourseNotFoundError,
    CourseRef,
    OSMClient,
    build_course_map,
    map_course,
)
from coursemapper.geo import centroid, distance_m

# Offsets in degrees; at this latitude 0.001 deg lat is ~111 m.
LAT, LON = 36.5680, -121.9500


def square(lat, lon, half=0.0001):
    ring = [
        (lat - half, lon - half),
        (lat - half, lon + half),
        (lat + half, lon + half),
        (lat + half, lon - half),
        (lat - half, lon - half),
    ]
    return [{"lat": a, "lon": b} for a, b in ring]


def way(id_, tags, geometry):
    return {"type": "way", "id": id_, "tags": tags, "geometry": geometry}


def line(*pts):
    return [{"lat": a, "lon": b} for a, b in pts]


HOLE1_TEE = (LAT, LON)
HOLE1_GREEN = (LAT + 0.003, LON)
HOLE2_TEE = (LAT + 0.0035, LON + 0.001)
HOLE2_GREEN = (LAT + 0.0035, LON + 0.005)

ELEMENTS = [
    way(10, {"golf": "hole", "ref": "1", "par": "4", "handicap": "7"}, line(HOLE1_TEE, HOLE1_GREEN)),
    way(20, {"golf": "hole", "ref": "2", "par": "5", "name": "Long One"}, line(HOLE2_TEE, HOLE2_GREEN)),
    # Hole 1: back tee at the line start, forward tee 40 m further up.
    way(11, {"golf": "tee", "tee": "blue"}, square(*HOLE1_TEE)),
    {"type": "node", "id": 12, "lat": LAT + 0.00036, "lon": LON, "tags": {"golf": "tee", "tee": "red"}},
    way(13, {"golf": "green"}, square(HOLE1_GREEN[0] + 0.00005, HOLE1_GREEN[1])),
    # Hole 2 has no tee or green features mapped.
    # A stray tee far from any hole start is ignored.
    way(99, {"golf": "tee"}, square(LAT - 0.01, LON - 0.01)),
]

COURSE = CourseRef(name="Test Links", osm_type="way", osm_id=1234)


class GeoTest(unittest.TestCase):
    def test_distance(self):
        d = distance_m(Coordinate(0, 0), Coordinate(1, 0))
        self.assertAlmostEqual(d, 111_195, delta=10)

    def test_centroid_of_square(self):
        pts = [Coordinate(p["lat"], p["lon"]) for p in square(LAT, LON)]
        c = centroid(pts)
        self.assertAlmostEqual(c.lat, LAT, places=7)
        self.assertAlmostEqual(c.lon, LON, places=7)

    def test_centroid_single_point(self):
        self.assertEqual(centroid([Coordinate(1, 2)]), Coordinate(1, 2))


class BuildCourseMapTest(unittest.TestCase):
    def setUp(self):
        self.course = build_course_map(COURSE, ELEMENTS)

    def test_holes_ordered_with_metadata(self):
        self.assertEqual([h.number for h in self.course.holes], [1, 2])
        h1, h2 = self.course.holes
        self.assertEqual((h1.par, h1.handicap), (4, 7))
        self.assertEqual((h2.par, h2.name), (5, "Long One"))

    def test_mapped_tees_and_green(self):
        h1 = self.course.holes[0]
        self.assertEqual([t.name for t in h1.tees], ["blue", "red"])  # back tee first
        self.assertTrue(all(t.source == "tee" for t in h1.tees))
        self.assertAlmostEqual(h1.tees[0].location.lat, LAT, places=6)
        self.assertEqual(h1.green_source, "green")
        self.assertAlmostEqual(h1.green_center.lat, HOLE1_GREEN[0] + 0.00005, places=6)
        self.assertAlmostEqual(h1.tees[0].distance_to_green_m, 339, delta=2)

    def test_falls_back_to_hole_line(self):
        h2 = self.course.holes[1]
        self.assertEqual(len(h2.tees), 1)
        self.assertEqual(h2.tees[0].source, "hole_line")
        self.assertEqual(h2.tees[0].location, Coordinate(*HOLE2_TEE))
        self.assertEqual(h2.green_source, "hole_line")
        self.assertEqual(h2.green_center, Coordinate(*HOLE2_GREEN))

    def test_double_green_uses_line_ends(self):
        end_a, end_b = (LAT, LON + 0.0002), (LAT, LON - 0.0002)
        elements = [
            way(1, {"golf": "hole", "ref": "1"}, line((LAT - 0.003, LON), end_a)),
            way(2, {"golf": "hole", "ref": "17"}, line((LAT + 0.003, LON), end_b)),
            way(3, {"golf": "green"}, square(LAT, LON, half=0.0003)),
        ]
        course = build_course_map(COURSE, elements)
        self.assertEqual(course.holes[0].green_center, Coordinate(*end_a))
        self.assertEqual(course.holes[1].green_center, Coordinate(*end_b))
        self.assertEqual(course.holes[0].green_source, "green")

    def test_relation_green(self):
        elements = [
            way(1, {"golf": "hole", "ref": "1"}, line((LAT - 0.003, LON), (LAT, LON))),
            {
                "type": "relation",
                "id": 5,
                "tags": {"golf": "green", "type": "multipolygon"},
                "members": [{"type": "way", "role": "outer", "geometry": square(LAT, LON + 0.0001)}],
            },
        ]
        green = build_course_map(COURSE, elements).holes[0].green_center
        self.assertAlmostEqual(green.lon, LON + 0.0001, places=6)

    def test_to_dict(self):
        d = self.course.to_dict()
        self.assertEqual(d["name"], "Test Links")
        self.assertIn("lat", d["holes"][0]["green_center"])


class FakeFetch:
    def __init__(self, nominatim, overpass):
        self.nominatim, self.overpass = nominatim, overpass
        self.calls = []

    def __call__(self, url, data):
        self.calls.append((url, data))
        return self.overpass if data is not None else self.nominatim


class MapCourseTest(unittest.TestCase):
    def test_end_to_end(self):
        fetch = FakeFetch(
            nominatim=[
                {"category": "place", "type": "city", "osm_type": "node", "osm_id": 1},
                {
                    "category": "leisure",
                    "type": "golf_course",
                    "osm_type": "relation",
                    "osm_id": 42,
                    "name": "Test Links",
                },
            ],
            overpass={"elements": ELEMENTS},
        )
        course = map_course("test links", client=OSMClient(fetch_json=fetch))
        self.assertEqual((course.osm_type, course.osm_id), ("relation", 42))
        self.assertEqual(len(course.holes), 2)
        overpass_query = fetch.calls[1][1]["data"]
        self.assertIn("area(3600000042)", overpass_query)

    def test_not_found(self):
        fetch = FakeFetch(nominatim=[{"category": "amenity", "type": "cafe"}], overpass=None)
        with self.assertRaises(CourseNotFoundError):
            map_course("nowhere", client=OSMClient(fetch_json=fetch))


if __name__ == "__main__":
    unittest.main()
