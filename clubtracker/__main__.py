"""Command line.

    python -m clubtracker import --db shots.db --user ann practice.csv
    python -m clubtracker averages --db shots.db --user ann
"""

import argparse
import sys

from .tracker import ClubTracker


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="clubtracker", description="Club distances from your shot history.")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="import a range-practice CSV")
    imp.add_argument("csv")
    avg = sub.add_parser("averages", help="show each club's averages")
    for p in (imp, avg):
        p.add_argument("--db", required=True, help="SQLite file holding the shot history")
        p.add_argument("--user", required=True, help="player id")
    args = parser.parse_args(argv)

    tracker = ClubTracker(args.db)
    if args.command == "import":
        r = tracker.import_range_csv(args.user, args.csv)
        print(f"Added {r.added} shots; {r.already_imported} were already imported; {len(r.skipped)} skipped.")
        for why in r.skipped:
            print(f"  skipped {why}")
    else:
        for s in tracker.club_averages(args.user).values():
            carry = f"{s.carry_yd:.0f}" if s.carry_yd is not None else "-"
            total = f"{s.total_yd:.0f}" if s.total_yd is not None else "-"
            print(f"{s.club:>6}  {s.shots:>3} shots  carry {carry:>4}  total {total:>4}  ({s.mishits} mishits left out)")
    tracker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
