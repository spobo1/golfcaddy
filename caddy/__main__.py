"""Command line: ``python -m caddy "Course Name" --hole 5 --user ann``."""

import argparse
import sys

from clubtracker import ClubTracker
from coursemapper import CourseNotFoundError, apply_scorecard, load_scorecard, map_course
from coursemapper.models import Coordinate

from .advice import advise_shot, tee_position


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="caddy", description="Suggest a club for a shot on a golf hole.")
    parser.add_argument("course", help="golf course name")
    parser.add_argument("--hole", type=int, required=True, help="hole number")
    parser.add_argument("--user", required=True, help="player id in the shot database")
    parser.add_argument("--db", default=":memory:", help="clubtracker SQLite file (default: none, so estimates only)")
    parser.add_argument("--skill", help="set the player's skill level first (beginner/intermediate/advanced/expert)")
    parser.add_argument("--scorecard", metavar="FILE", help="scorecard JSON, to use --tee colours")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--tee", metavar="COLOUR", help="play from this tee colour (default: back tee)")
    where.add_argument("--at", metavar="LAT,LON", help="play from this GPS position")
    args = parser.parse_args(argv)

    try:
        course = map_course(args.course)
    except CourseNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    if args.scorecard:
        apply_scorecard(course, load_scorecard(args.scorecard))
    hole = next((h for h in course.holes if h.number == args.hole), None)
    if hole is None:
        print(f"{course.name} has no hole {args.hole} mapped", file=sys.stderr)
        return 1
    if args.at:
        lat, lon = (float(v) for v in args.at.split(","))
        position = Coordinate(lat, lon)
    else:
        position = tee_position(hole, args.tee)

    tracker = ClubTracker(args.db)
    if args.skill:
        tracker.set_skill_level(args.user, args.skill)
    advice = advise_shot(tracker, args.user, hole, position)

    front = f"{advice.to_front_yd:.0f} front, " if advice.to_front_yd is not None else ""
    back = f", {advice.to_back_yd:.0f} back" if advice.to_back_yd is not None else ""
    print(f"{course.name}, hole {hole.number} (par {hole.par}): {front}{advice.to_center_yd:.0f} centre{back}")
    for h in advice.hazards:
        print(f"  {h.kind.replace('_', ' ')} {h.side}: {h.reach_yd:.0f} to reach, {h.carry_yd:.0f} to carry")
    d = advice.distance
    basis = f"your average of {d.shots} shots" if d.source == "history" else f"{d.skill_level} estimate"
    print(f"Club: {advice.club} ({d.carry_yd:.0f} carry, {d.total_yd:.0f} total, {basis})")
    print(advice.reason)
    tracker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
