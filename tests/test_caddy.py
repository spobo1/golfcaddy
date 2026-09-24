import unittest

from caddy import advise_shot, hazards_ahead, tee_position
from clubtracker import ClubTracker
from coursemapper.models import Coordinate, Hazard, Hole, TeeBox

LAT, LON = 41.1, -73.5
M_PER_YD = 0.9144
LAT_PER_M = 1 / 111_195.0


def at(north_yd, east_yd=0.0):
    """A point this many yards north and east of the tee."""
    import math

    dlat = north_yd * M_PER_YD * LAT_PER_M
    dlon = east_yd * M_PER_YD * LAT_PER_M / math.cos(math.radians(LAT))
    return Coordinate(LAT + dlat, LON + dlon)


def hazard(kind, north_from, north_to, east_from, east_to):
    outline = [at(north_from, east_from), at(north_from, east_to), at(north_to, east_to), at(north_to, east_from), at(north_from, east_from)]
    return Hazard(kind, at((north_from + north_to) / 2, (east_from + east_to) / 2), outline, "", 0, 0, 0)


def hole(green_yd, hazards=(), depth_yd=30):
    return Hole(
        number=1,
        tees=[TeeBox(at(0), colours=["Blue"]), TeeBox(at(20), colours=["White", "Red"])],
        green_center=at(green_yd),
        green_front=at(green_yd - depth_yd / 2),
        green_back=at(green_yd + depth_yd / 2),
        hazards=list(hazards),
    )


# Carry, total in yards.
BAG = {"driver": (230, 250), "5i": (170, 175), "7i": (150, 155), "9i": (125, 128), "pw": (110, 112)}


class CaddyTest(unittest.TestCase):
    def setUp(self):
        self.tracker = ClubTracker()
        self.addCleanup(self.tracker.close)
        for club, (carry, total) in BAG.items():
            self.tracker.record_shot("ann", club, carry_yd=carry, total_yd=total)

    def advise(self, h, position=None, **kw):
        return advise_shot(self.tracker, "ann", h, position or at(0), clubs=list(BAG), **kw)

    def test_distances_to_front_centre_and_back(self):
        a = self.advise(hole(155))
        self.assertAlmostEqual(a.to_center_yd, 155, delta=0.3)
        self.assertAlmostEqual(a.to_front_yd, 140, delta=0.3)
        self.assertAlmostEqual(a.to_back_yd, 170, delta=0.3)

    def test_club_to_the_centre_when_nothing_in_the_way(self):
        a = self.advise(hole(155))
        self.assertEqual((a.club, a.plan), ("7i", "target"))
        self.assertEqual(a.reason, "7 iron finishes at the centre of the green.")

    def test_more_club_to_carry_water_in_front(self):
        water = hazard("water", 135, 148, -20, 20)
        a = self.advise(hole(155, [water]))
        # The 7 iron (150 carry) would land in water that needs 148 + 5 leeway.
        self.assertEqual((a.club, a.plan), ("5i", "carry"))
        self.assertEqual(a.reason, "Take 5 iron to carry the water (148 to carry, 5 iron carries 170).")
        (ahead,) = a.hazards
        self.assertEqual(ahead.side, "crossing")
        self.assertAlmostEqual(ahead.reach_yd, 135, delta=0.5)
        self.assertAlmostEqual(ahead.carry_yd, 148, delta=0.5)

    def test_lay_up_when_hazard_cannot_be_carried(self):
        water = hazard("water", 160, 185, -20, 20)
        a = self.advise(hole(200, [water]))
        # The driver would carry it but finish 35 over the back; laying up is better.
        self.assertEqual((a.club, a.plan), ("9i", "layup"))
        self.assertEqual(a.reason, "Lay up with 9 iron, about 32 short of the water (160 to reach).")

    def test_hazard_beside_the_line_is_listed_but_not_avoided(self):
        bunker = hazard("bunker", 140, 150, 15, 25)
        a = self.advise(hole(155, [bunker]))
        self.assertEqual(a.club, "7i")
        self.assertEqual([(h.kind, h.side) for h in a.hazards], [("bunker", "right")])

    def test_driver_only_when_green_out_of_reach(self):
        a = self.advise(hole(400))
        self.assertEqual((a.club, a.plan), ("driver", "target"))
        self.assertEqual(a.reason, "The green is out of reach; driver leaves about 150 to the centre.")
        self.assertEqual(self.advise(hole(400), include_driver=False).club, "5i")
        # Within reach of the other clubs, the driver isn't offered unless asked.
        self.assertEqual(self.advise(hole(165)).club, "5i")
        self.assertEqual(self.advise(hole(235), include_driver=True).club, "driver")

    def test_every_club_at_risk(self):
        water = hazard("water", 60, 260, -30, 30)
        a = self.advise(hole(270, [water]))
        self.assertEqual((a.club, a.plan), ("driver", "no_safe_club"))
        self.assertEqual(a.reason, "Every club risks the water; driver finishes closest to the green.")

    def test_from_a_position_on_the_fairway(self):
        # 100 yd up the fairway and 10 yd right: 55 yd left to the centre.
        a = self.advise(hole(155), position=at(100, 10))
        self.assertAlmostEqual(a.to_center_yd, (55**2 + 10**2) ** 0.5, delta=0.3)
        self.assertEqual(a.club, "pw")

    def test_hazards_behind_player_are_ignored(self):
        bunker = hazard("bunker", 10, 30, -10, 10)
        self.assertEqual(hazards_ahead(hole(155, [bunker]), at(60)), [])

    def test_tee_position(self):
        h = hole(155)
        self.assertEqual(tee_position(h, "red"), at(20))
        self.assertEqual(tee_position(h, "Blue"), at(0))
        self.assertEqual(tee_position(h), at(0))
        self.assertEqual(tee_position(h, "Gold"), at(0))


if __name__ == "__main__":
    unittest.main()
