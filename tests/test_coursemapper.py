import unittest
import urllib.error

from coursemapper import (
    Coordinate,
    CourseNotFoundError,
    CourseRef,
    OSMClient,
    build_course_map,
    map_course,
)
from coursemapper.geo import centroid, distance_m, point_in_rings

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

    def test_point_in_rings_with_hole(self):
        outer = [Coordinate(p["lat"], p["lon"]) for p in square(LAT, LON, half=0.01)]
        inner = [Coordinate(p["lat"], p["lon"]) for p in square(LAT, LON, half=0.001)]
        self.assertTrue(point_in_rings(Coordinate(LAT + 0.005, LON), [outer, inner]))
        self.assertFalse(point_in_rings(Coordinate(LAT, LON), [outer, inner]))
        self.assertFalse(point_in_rings(Coordinate(LAT + 0.02, LON), [outer, inner]))


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

    def test_green_front_and_back(self):
        h1, h2 = self.course.holes
        green_lat = HOLE1_GREEN[0] + 0.00005
        self.assertAlmostEqual(h1.green_front.lat, green_lat - 0.0001, places=6)
        self.assertAlmostEqual(h1.green_back.lat, green_lat + 0.0001, places=6)
        self.assertAlmostEqual(h1.green_front.lon, LON, places=6)
        back_tee = h1.tees[0]
        self.assertAlmostEqual(back_tee.distance_to_green_front_m, back_tee.distance_to_green_m - 11.1, delta=0.2)
        self.assertAlmostEqual(back_tee.distance_to_green_back_m, back_tee.distance_to_green_m + 11.1, delta=0.2)
        # No green outline mapped for hole 2.
        self.assertIsNone(h2.green_front)
        self.assertIsNone(h2.tees[0].distance_to_green_front_m)

    def test_green_depth_follows_dogleg_approach(self):
        # Dogleg: east from the tee, then north into a wide, shallow green.
        # Measured from the south the green is ~22 m deep; from the tee
        # (west) it would be ~71 m wide.
        corner = (LAT, LON + 0.002)
        end = (LAT + 0.002, LON + 0.002)
        elements = [
            way(1, {"golf": "hole", "ref": "1"}, line((LAT, LON), corner, end)),
            way(2, {"golf": "green"}, [
                {"lat": end[0] + dlat, "lon": end[1] + dlon}
                for dlat, dlon in ((-0.0001, -0.0004), (-0.0001, 0.0004), (0.0001, 0.0004), (0.0001, -0.0004), (-0.0001, -0.0004))
            ]),
        ]
        (hole,) = build_course_map(COURSE, elements).holes
        self.assertAlmostEqual(distance_m(hole.green_front, hole.green_back), 22.2, delta=0.5)
        self.assertAlmostEqual(hole.green_front.lon, end[1], places=6)

    def test_fairways_go_to_nearest_hole(self):
        holes = [
            way(1, {"golf": "hole", "ref": "1"}, line((LAT, LON), (LAT + 0.003, LON))),
            way(2, {"golf": "hole", "ref": "2"}, line((LAT, LON + 0.001), (LAT + 0.003, LON + 0.001))),
        ]
        fairway1 = way(10, {"golf": "fairway"}, square(LAT + 0.0015, LON + 0.0001, half=0.0003))
        fairway2 = way(11, {"golf": "fairway"}, square(LAT + 0.0015, LON + 0.0009, half=0.0003))
        stray = way(12, {"golf": "fairway"}, square(LAT + 0.0015, LON + 0.004))
        h1, h2 = build_course_map(COURSE, [*holes, fairway1, fairway2, stray]).holes
        self.assertEqual(len(h1.fairways), 1)
        self.assertEqual(len(h2.fairways), 1)
        self.assertAlmostEqual(centroid(h1.fairways[0]).lon, LON + 0.0001, places=6)

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

    def test_hole_length(self):
        self.assertAlmostEqual(self.course.holes[0].length_m, 333.6, delta=1)

    def test_tee_ref_picks_matching_hole(self):
        # Two holes start near the tee; the closer one has the wrong number.
        elements = [
            way(1, {"golf": "hole", "ref": "1"}, line((LAT, LON), (LAT + 0.003, LON))),
            way(2, {"golf": "hole", "ref": "2"}, line((LAT, LON + 0.0006), (LAT - 0.003, LON + 0.0006))),
            {"type": "node", "id": 3, "lat": LAT, "lon": LON + 0.0001, "tags": {"golf": "tee", "ref": "2"}},
        ]
        h1, h2 = build_course_map(COURSE, elements).holes
        self.assertEqual(h1.tees[0].source, "hole_line")
        self.assertEqual(h2.tees[0].location, Coordinate(LAT, LON + 0.0001))

    def test_tee_beyond_hole_length_goes_to_other_hole(self):
        # The tee is 55 m behind hole 1's back tee, so it cannot be a hole 1
        # tee; it is a forward tee for hole 2, whose line starts 70 m away.
        elements = [
            way(1, {"golf": "hole", "ref": "1"}, line((LAT, LON), (LAT + 0.003, LON))),
            way(2, {"golf": "hole", "ref": "2"}, line((LAT - 0.0005, LON + 0.0008), (LAT - 0.0005, LON - 0.004))),
            {"type": "node", "id": 3, "lat": LAT - 0.0005, "lon": LON, "tags": {"golf": "tee"}},
        ]
        h1, h2 = build_course_map(COURSE, elements).holes
        self.assertEqual(h1.tees[0].source, "hole_line")
        self.assertEqual([t.source for t in h2.tees], ["tee"])

    def test_tee_behind_middle_tee_line_is_kept(self):
        # The line starts at a middle tee; the back tee 50 m behind it has no
        # better hole to go to, so it stays.
        elements = [
            way(1, {"golf": "hole", "ref": "1"}, line((LAT, LON), (LAT + 0.003, LON))),
            {"type": "node", "id": 3, "lat": LAT - 0.00045, "lon": LON, "tags": {"golf": "tee"}},
        ]
        (h1,) = build_course_map(COURSE, elements).holes
        self.assertEqual([t.source for t in h1.tees], ["tee"])

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


class HazardTest(unittest.TestCase):
    # Hole 1 runs due north for ~333 m; hole 2 runs parallel 90 m to the east.
    HOLE1 = way(1, {"golf": "hole", "ref": "1"}, line((LAT, LON), (LAT + 0.003, LON)))
    HOLE2 = way(2, {"golf": "hole", "ref": "2"}, line((LAT, LON + 0.001), (LAT + 0.003, LON + 0.001)))

    def hazards(self, *extra, holes=(HOLE1,)):
        course = build_course_map(COURSE, [*holes, *extra])
        return [h.hazards for h in course.holes]

    def test_bunker_side_and_distances(self):
        # 25 m right of the line (east when heading north), ~220 m out.
        bunker = way(10, {"golf": "bunker"}, square(LAT + 0.002, LON + 0.0003))
        (hazards,) = self.hazards(bunker)
        (h,) = hazards
        self.assertEqual((h.kind, h.side), ("bunker", "right"))
        self.assertAlmostEqual(h.reach_from_back_tee_m, 213, delta=3)
        self.assertAlmostEqual(h.carry_from_back_tee_m, 238, delta=3)
        self.assertAlmostEqual(h.distance_to_green_m, 115, delta=3)

    def test_cross_bunker_and_left_water_sorted_by_reach(self):
        cross = way(10, {"golf": "bunker"}, square(LAT + 0.001, LON))
        pond = way(11, {"natural": "water"}, square(LAT + 0.0005, LON - 0.0004))
        (hazards,) = self.hazards(cross, pond)
        self.assertEqual([(h.kind, h.side) for h in hazards], [("water", "left"), ("bunker", "crossing")])

    def test_far_bunker_ignored(self):
        far = way(10, {"golf": "bunker"}, square(LAT + 0.001, LON + 0.003))
        self.assertEqual(self.hazards(far), [[]])

    def test_bunker_goes_to_nearest_hole_only(self):
        bunker = way(10, {"golf": "bunker"}, square(LAT + 0.001, LON + 0.0003))
        h1, h2 = self.hazards(bunker, holes=(self.HOLE1, self.HOLE2))
        self.assertEqual((len(h1), len(h2)), (1, 0))

    def test_water_between_holes_counts_for_both(self):
        pond = way(10, {"golf": "lateral_water_hazard"}, square(LAT + 0.001, LON + 0.0005, half=0.0002))
        h1, h2 = self.hazards(pond, holes=(self.HOLE1, self.HOLE2))
        self.assertEqual([(h.kind, h.side) for h in h1], [("lateral_water", "right")])
        self.assertEqual([(h.kind, h.side) for h in h2], [("lateral_water", "left")])

    def test_pond_mapped_twice_counts_once(self):
        hazard = way(10, {"golf": "water_hazard"}, square(LAT + 0.001, LON - 0.0003))
        water = way(11, {"natural": "water"}, square(LAT + 0.001, LON - 0.0003, half=0.00012))
        (hazards,) = self.hazards(hazard, water)
        self.assertEqual([h.kind for h in hazards], ["water"])


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
        self.assertIn("relation(42);\nmap_to_area->.course;", overpass_query)

    def test_falls_back_to_course_near_clubhouse(self):
        nearby = {
            "elements": [
                {"type": "way", "id": 7, "tags": {"name": "Other Course"}, "center": {"lat": LAT, "lon": LON}},
                {
                    "type": "relation",
                    "id": 8,
                    "tags": {"name": "The Test Golf Course"},
                    "center": {"lat": LAT + 0.01, "lon": LON},
                },
            ]
        }
        clubhouse = {
            "category": "amenity",
            "type": "restaurant",
            "osm_type": "way",
            "osm_id": 1,
            "lat": str(LAT),
            "lon": str(LON),
        }
        overpass = iter([nearby, {"elements": ELEMENTS}])
        client = OSMClient(fetch_json=lambda url, data: next(overpass) if data else [clubhouse])
        course = map_course("Test Links", client=client)
        # The name match (ignoring generic words) wins over the closer course.
        self.assertEqual((course.name, course.osm_type, course.osm_id), ("The Test Golf Course", "relation", 8))
        self.assertEqual(len(course.holes), 2)

    def test_falls_back_to_osm_api_when_overpass_unreachable(self):
        self._check_osm_api_fallback(overpass_result=None)

    def test_falls_back_to_osm_api_when_overpass_finds_no_holes(self):
        self._check_osm_api_fallback(overpass_result={"elements": []})

    def _check_osm_api_fallback(self, overpass_result):
        """overpass_result=None means Overpass is unreachable."""
        def node(id_, lat, lon, tags=None):
            return {"type": "node", "id": id_, "lat": lat, "lon": lon, "tags": tags or {}}

        corners = [(LAT - 0.005, LON - 0.005), (LAT - 0.005, LON + 0.005), (LAT + 0.005, LON + 0.005), (LAT + 0.005, LON - 0.005)]
        boundary_nodes = [node(100 + i, a, b) for i, (a, b) in enumerate(corners)]
        boundary = {"type": "way", "id": 50, "nodes": [100, 101, 102, 103, 100], "tags": {"leisure": "golf_course"}}
        map_elements = boundary_nodes + [
            node(1, *HOLE1_TEE),
            node(2, *HOLE1_GREEN),
            {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"golf": "hole", "ref": "1"}},
            node(3, LAT, LON, {"golf": "tee", "tee": "blue"}),
            # Another course's hole outside the boundary is excluded.
            node(4, LAT + 0.02, LON),
            node(5, LAT + 0.023, LON),
            {"type": "way", "id": 11, "nodes": [4, 5], "tags": {"golf": "hole", "ref": "1"}},
        ]
        urls = []

        def fetch(url, data):
            urls.append(url)
            if data is not None:
                if overpass_result is None:
                    raise urllib.error.URLError("connection reset")
                return overpass_result
            if url.endswith("/way/50/full.json"):
                return {"elements": boundary_nodes + [boundary]}
            if "/map.json?bbox=" in url:
                return {"elements": map_elements}
            return [{"category": "leisure", "type": "golf_course", "osm_type": "way", "osm_id": 50, "name": "T"}]

        course = map_course("T", client=OSMClient(fetch_json=fetch))
        self.assertEqual(len(course.holes), 1)
        self.assertEqual(course.holes[0].tees[0].name, "blue")
        self.assertIn("bbox=-121.9560000,36.5620000,-121.9440000,36.5740000", urls[-1])

    def test_not_found(self):
        fetch = FakeFetch(nominatim=[{"category": "amenity", "type": "cafe"}], overpass=None)
        with self.assertRaises(CourseNotFoundError):
            map_course("nowhere", client=OSMClient(fetch_json=fetch))


if __name__ == "__main__":
    unittest.main()
