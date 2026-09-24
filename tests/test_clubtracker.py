import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from clubtracker import CLUBS, ClubTracker, LaunchData, normalize_club

T0 = datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)


class NormalizeClubTest(unittest.TestCase):
    def test_common_names(self):
        cases = {
            "Driver": "driver", "7 iron": "7i", "7-Iron": "7i", "3 Wood": "3w",
            "4 hybrid": "4h", "PW": "pw", "sand wedge": "sw", "Gap": "gw", "lw": "lw",
        }
        for name, code in cases.items():
            self.assertEqual(normalize_club(name), code, name)

    def test_unknown_club(self):
        for name in ("putter", "12 iron", "banana"):
            with self.assertRaises(ValueError):
                normalize_club(name)


class ClubTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tracker = ClubTracker()
        self.addCleanup(self.tracker.close)

    def test_history_newest_first_and_filtered_by_club(self):
        t = self.tracker
        t.record_shot("ann", "7 iron", carry_yd=150, recorded_at=T0)
        t.record_shot("ann", "driver", total_yd=240, recorded_at=T0 + timedelta(minutes=1))
        t.record_shot("ann", "7i", carry_yd=145, recorded_at=T0 + timedelta(minutes=2))
        t.record_shot("bob", "7i", carry_yd=120, recorded_at=T0)

        self.assertEqual([(s.club, s.carry_yd or s.total_yd) for s in t.shots("ann")], [("7i", 145), ("driver", 240), ("7i", 150)])
        self.assertEqual([s.carry_yd for s in t.shots("ann", club="7-iron")], [145, 150])
        self.assertEqual(len(t.shots("ann", limit=1)), 1)
        self.assertEqual(t.shots("ann")[0].recorded_at, T0 + timedelta(minutes=2))

    def test_launch_data_round_trips(self):
        launch = LaunchData(launch_angle_deg=12.5, ball_speed_mph=165, spin_rate_rpm=2600, offline_yd=-4)
        self.tracker.record_shot("ann", "driver", carry_yd=250, total_yd=270, launch=launch, recorded_at=T0)
        (shot,) = self.tracker.shots("ann")
        self.assertEqual(shot.launch, launch)
        self.assertIsNone(shot.launch.club_path_deg)

    def test_averages_per_club(self):
        t = self.tracker
        t.record_shot("ann", "7i", carry_yd=150, total_yd=155, launch=LaunchData(launch_angle_deg=17))
        t.record_shot("ann", "7i", carry_yd=140, launch=LaunchData(launch_angle_deg=19, spin_rate_rpm=7000))
        t.record_shot("ann", "driver", total_yd=240)

        stats = t.club_averages("ann")
        self.assertEqual(list(stats), ["driver", "7i"])  # bag order
        seven = stats["7i"]
        self.assertEqual((seven.shots, seven.carry_yd, seven.total_yd), (2, 145, 155))
        self.assertEqual(seven.launch.launch_angle_deg, 18)
        self.assertEqual(seven.launch.spin_rate_rpm, 7000)
        self.assertIsNone(seven.launch.ball_speed_mph)
        self.assertIsNone(stats["driver"].carry_yd)

    def test_distance_from_history(self):
        t = self.tracker
        t.record_shot("ann", "7i", carry_yd=150)
        t.record_shot("ann", "7i", carry_yd=160)
        d = t.club_distance("ann", "7 iron")
        self.assertEqual((d.source, d.shots, d.carry_yd), ("history", 2, 155))
        self.assertEqual(d.total_yd, round(155 * 1.03, 1))  # typical 7-iron roll

    def test_distance_fills_missing_carry_from_total(self):
        self.tracker.record_shot("ann", "driver", total_yd=270)
        d = self.tracker.club_distance("ann", "driver")
        self.assertEqual((d.total_yd, d.carry_yd), (270, 250))

    def test_estimate_for_player_without_history(self):
        t = self.tracker
        t.set_skill_level("new", "Beginner")
        d = t.club_distance("new", "driver")
        self.assertEqual((d.source, d.skill_level, d.carry_yd, d.shots), ("estimate", "beginner", 175, 0))
        t.set_skill_level("new", "expert")
        self.assertEqual(t.club_distance("new", "driver").carry_yd, 255)

    def test_estimate_uses_default_skill_when_unset(self):
        d = self.tracker.club_distance("nobody", "pw")
        self.assertEqual((d.source, d.skill_level, d.carry_yd), ("estimate", "intermediate", 100))

    def test_bag_mixes_history_and_estimates(self):
        t = self.tracker
        t.set_skill_level("ann", "advanced")
        t.record_shot("ann", "7i", carry_yd=158)
        bag = t.bag("ann")
        self.assertEqual([d.club for d in bag], list(CLUBS))
        by_club = {d.club: d for d in bag}
        self.assertEqual((by_club["7i"].source, by_club["7i"].carry_yd), ("history", 158))
        self.assertEqual((by_club["8i"].source, by_club["8i"].carry_yd), ("estimate", 140))

    def test_estimates_get_shorter_down_the_bag(self):
        for level in ("beginner", "intermediate", "advanced", "expert"):
            self.tracker.set_skill_level("p", level)
            woods_and_irons = [d.carry_yd for d in self.tracker.bag("p") if not d.club.endswith(("w", "h")) or d.club == "driver"]
            self.assertEqual(woods_and_irons, sorted(woods_and_irons, reverse=True), level)

    def test_delete_shot(self):
        shot = self.tracker.record_shot("ann", "sw", carry_yd=85)
        self.assertTrue(self.tracker.delete_shot(shot.id))
        self.assertFalse(self.tracker.delete_shot(shot.id))
        self.assertEqual(self.tracker.club_distance("ann", "sw").source, "estimate")

    def test_rejects_bad_input(self):
        t = self.tracker
        with self.assertRaises(ValueError):
            t.record_shot("ann", "7i")
        with self.assertRaises(ValueError):
            t.record_shot("ann", "7i", carry_yd=-5)
        with self.assertRaises(ValueError):
            t.record_shot("ann", "putter", carry_yd=5)
        with self.assertRaises(ValueError):
            t.set_skill_level("ann", "pro")

    def test_history_persists_in_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shots.db")
            first = ClubTracker(path)
            first.set_skill_level("ann", "expert")
            first.record_shot("ann", "9i", carry_yd=140)
            first.close()
            second = ClubTracker(path)
            self.addCleanup(second.close)
            self.assertEqual(second.skill_level("ann"), "expert")
            self.assertEqual(second.club_distance("ann", "9i").carry_yd, 140)


if __name__ == "__main__":
    unittest.main()
