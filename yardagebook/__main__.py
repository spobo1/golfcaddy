"""Command line: ``python -m yardagebook sterling-farms`` or ``python -m yardagebook --all``.

Courses are listed in yardagebook/courses.json. Pages are written to build/.
"""

import argparse
import json
import os
import sys

from .build import build_page

COURSES = os.path.join(os.path.dirname(__file__), "courses.json")


def main(argv=None) -> int:
    with open(COURSES) as f:
        courses = json.load(f)
    parser = argparse.ArgumentParser(prog="yardagebook", description="Build yardage book and caddy pages.")
    parser.add_argument("courses", nargs="*", help=f"course keys from courses.json: {', '.join(courses)}")
    parser.add_argument("--all", action="store_true", help="build every course in courses.json")
    parser.add_argument("--out-dir", default="build", help="where to write pages (default: build/)")
    parser.add_argument("--no-aerial", action="store_true", help="skip the aerial photo")
    args = parser.parse_args(argv)

    keys = list(courses) if args.all else args.courses
    if not keys:
        parser.error("name at least one course, or use --all")
    unknown = [k for k in keys if k not in courses]
    if unknown:
        parser.error(f"unknown course(s): {', '.join(unknown)}")

    for key in keys:
        c = courses[key]
        summary = build_page(
            query=c["query"],
            scorecard_path=c["scorecard"],
            out_path=os.path.join(args.out_dir, f"{key}.html"),
            title=c["title"],
            place=c["place"],
            default_tee=c["default_tee"],
            aerial=not args.no_aerial,
        )
        print(f"{summary['course']}: {summary['holes']} holes, {summary['hazards']} hazards -> {summary['page']}"
              + (f" (+ {summary['aerial']})" if summary["aerial"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
