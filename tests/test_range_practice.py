import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

from clubtracker import ClubTracker

SCRIPT = os.path.join(os.path.dirname(__file__), "..", ".claude", "skills", "range-practice", "scripts", "range_log.py")


class StrikeTest(unittest.TestCase):
    def setUp(self):
        self.tracker = ClubTracker()
        self.addCleanup(self.tracker.close)

    def test_mishits_kept_but_left_out_of_averages(self):
        t = self.tracker
        t.record_shot("ann", "7i", carry_yd=150, strike="good")
        t.record_shot("ann", "7i", carry_yd=146, strike="OK")
        t.record_shot("ann", "7i", carry_yd=60, strike="mishit")
        stats = t.club_averages("ann")["7i"]
        self.assertEqual((stats.shots, stats.mishits, stats.carry_yd), (2, 1, 148))
        self.assertEqual([s.strike for s in t.shots("ann")], ["mishit", "ok", "good"])

    def test_only_mishits_falls_back_to_estimate(self):
        self.tracker.record_shot("ann", "pw", carry_yd=30, strike="mishit")
        self.assertEqual(self.tracker.club_distance("ann", "pw").source, "estimate")

    def test_rejects_unknown_strike(self):
        with self.assertRaises(ValueError):
            self.tracker.record_shot("ann", "7i", carry_yd=150, strike="amazing")

    def test_upgrades_older_database(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.db")
            db = sqlite3.connect(path)
            db.executescript(
                "CREATE TABLE shots (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, club TEXT NOT NULL, "
                "recorded_at TEXT NOT NULL, carry_yd REAL, total_yd REAL, ball_speed_mph REAL, club_speed_mph REAL, "
                "smash_factor REAL, launch_angle_deg REAL, launch_direction_deg REAL, spin_rate_rpm REAL, "
                "spin_axis_deg REAL, attack_angle_deg REAL, club_path_deg REAL, face_angle_deg REAL, apex_yd REAL, "
                "descent_angle_deg REAL, offline_yd REAL);"
                "INSERT INTO shots (user_id, club, recorded_at, carry_yd) VALUES ('ann', '9i', '2026-01-01T00:00:00+00:00', 130);"
            )
            db.commit()
            db.close()
            t = ClubTracker(path)
            self.addCleanup(t.close)
            t.record_shot("ann", "9i", carry_yd=40, strike="mishit")
            self.assertEqual(t.club_averages("ann")["9i"].carry_yd, 130)


class RangeLogScriptTest(unittest.TestCase):
    def run_script(self, d, session, history=None):
        path = os.path.join(d, "session.json")
        with open(path, "w") as f:
            json.dump(session, f)
        out = os.path.join(d, "range-log.csv")
        cmd = [sys.executable, SCRIPT, "--session", path, "--out", out]
        if history:
            cmd += ["--history", history]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        with open(out, newline="") as f:
            return list(csv.DictReader(f)), result.stdout, out

    def test_session_to_csv_to_clubtracker(self):
        session = {
            "date": "2026-09-25", "time": "17:30", "distance_type": "carry",
            "shots": [
                {"club": "7i", "distance": 150, "strike": "good"},
                {"club": "seven iron", "distance": 146, "strike": "ok"},
                {"club": "7 iron", "distance": 90, "strike": "mishit", "notes": "topped"},
                {"club": "Driver", "distance": 230, "strike": "good", "launch_angle_deg": 12.5, "ball_speed_mph": 150},
                {"club": "52 degree", "distance": 95, "strike": "good"},
            ],
        }
        with tempfile.TemporaryDirectory() as d:
            rows, summary, out = self.run_script(d, session)
            self.assertEqual([r["shot_id"] for r in rows][:2], ["2026-09-25-s1-001", "2026-09-25-s1-002"])
            self.assertEqual(rows[0]["club"], "7 iron")
            self.assertEqual(rows[3]["launch_angle_deg"], "12.5")
            self.assertIn("| 7 iron | 3 | 1 / 1 / 1 | 148 | 150 | 146 | - |", summary)
            self.assertIn("won't import it: 52 degree", summary)

            # A second session the same day continues the file and numbering.
            again = dict(session, time="19:00", shots=[{"club": "7i", "distance": 156, "strike": "good"}])
            history = os.path.join(d, "history.csv")
            os.replace(out, history)
            rows2, summary2, out2 = self.run_script(d, again, history=history)
            self.assertEqual(len(rows2), 6)
            self.assertEqual(rows2[-1]["shot_id"], "2026-09-25-s2-001")
            self.assertIn("| 7 iron | 1 | 1 / 0 / 0 | 156 | 156 | 156 | 148 (+8) |", summary2)

            tracker = ClubTracker()
            self.addCleanup(tracker.close)
            result = tracker.import_range_csv("ann", out2)
            self.assertEqual((result.added, result.already_imported, len(result.skipped)), (5, 0, 1))
            self.assertIn("52 degree", result.skipped[0])
            again_result = tracker.import_range_csv("ann", out2)
            self.assertEqual((again_result.added, again_result.already_imported), (0, 5))
            seven = tracker.club_averages("ann")["7i"]
            self.assertEqual((seven.shots, seven.mishits, seven.carry_yd), (3, 1, round((150 + 146 + 156) / 3, 1)))
            self.assertEqual(tracker.club_averages("ann")["driver"].launch.launch_angle_deg, 12.5)

    def test_bad_strike_is_refused(self):
        session = {"date": "2026-09-25", "shots": [{"club": "7i", "distance": 150, "strike": "great"}]}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_script(d, session)


if __name__ == "__main__":
    unittest.main()
