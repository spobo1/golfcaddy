"""Command line entry point: ``python -m coursemapper "Course Name"``."""

import argparse
import json
import sys

from . import CourseNotFoundError, apply_scorecard, load_scorecard, map_course


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="coursemapper",
        description="Print GPS coordinates of each hole's tee boxes and green centre as JSON.",
    )
    parser.add_argument("course", help='golf course name, e.g. "Pebble Beach Golf Links"')
    parser.add_argument(
        "--scorecard",
        metavar="FILE",
        help="scorecard JSON with each tee colour's yardages (see scorecards/), used to label tee boxes",
    )
    args = parser.parse_args(argv)
    try:
        course_map = map_course(args.course)
    except CourseNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    if args.scorecard:
        apply_scorecard(course_map, load_scorecard(args.scorecard))
    json.dump(course_map.to_dict(), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
