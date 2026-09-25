#!/usr/bin/env python3
"""Write a range practice session to the player's CSV log and summarise it.

    python range_log.py --session session.json --out range-log.csv [--history old-range-log.csv]

session.json:
    {"date": "2026-09-25", "time": "17:30", "distance_type": "carry",
     "shots": [{"club": "7 iron", "distance": 152, "strike": "good", "notes": "",
                "launch_angle_deg": 17.5}, ...]}

The output CSV holds the history (if given) followed by this session, so the
player keeps one growing file. Prints a Markdown summary: this session per
club, and how it compares with the history. Mishits are listed but left out
of averages. Standard library only.
"""

import argparse
import csv
import json
import re
import sys

LAUNCH = [
    "ball_speed_mph", "club_speed_mph", "smash_factor", "launch_angle_deg", "launch_direction_deg",
    "spin_rate_rpm", "spin_axis_deg", "attack_angle_deg", "club_path_deg", "face_angle_deg",
    "apex_yd", "descent_angle_deg", "offline_yd",
]
COLUMNS = ["shot_id", "date", "time", "club", "distance_yd", "distance_type", "strike", "notes", *LAUNCH]
STRIKES = ("good", "ok", "mishit")

# Clubs in bag order, with the names used in the log. These match what the
# golfcaddy clubtracker understands, so the file imports cleanly.
CLUBS = {
    "driver": "Driver", "3w": "3 wood", "5w": "5 wood", "7w": "7 wood",
    "3h": "3 hybrid", "4h": "4 hybrid", "5h": "5 hybrid",
    "3i": "3 iron", "4i": "4 iron", "5i": "5 iron", "6i": "6 iron", "7i": "7 iron", "8i": "8 iron", "9i": "9 iron",
    "pw": "PW", "gw": "GW", "sw": "SW", "lw": "LW",
}
ALIASES = {
    "d": "driver", "dr": "driver", "1w": "driver", "p": "pw", "pitchingwedge": "pw", "pitching": "pw",
    "g": "gw", "gapwedge": "gw", "gap": "gw", "aw": "gw", "approachwedge": "gw", "s": "sw", "sandwedge": "sw",
    "sand": "sw", "l": "lw", "lobwedge": "lw", "lob": "lw",
}
NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
KIND = {"wood": "w", "w": "w", "hybrid": "h", "hy": "h", "h": "h", "rescue": "h", "iron": "i", "i": "i"}


def club_code(name):
    """The club's code (e.g. "7i"), or None if it isn't one the tracker knows."""
    key = str(name).strip().lower()
    for word, digit in NUMBER_WORDS.items():
        key = re.sub(rf"\b{word}\b", digit, key)
    key = re.sub(r"[\s\-_]", "", key)
    if key in CLUBS:
        return key
    if key in ALIASES:
        return ALIASES[key]
    m = re.fullmatch(r"(\d+)([a-z]+)", key)
    if m and m.group(2) in KIND and m.group(1) + KIND[m.group(2)] in CLUBS:
        return m.group(1) + KIND[m.group(2)]
    return None


def club_label(name):
    code = club_code(name)
    return CLUBS[code] if code else str(name).strip()


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def session_rows(session, history):
    date = session["date"]
    # Number this session after any earlier ones on the same day.
    earlier = [int(m.group(1)) for r in history
               for m in [re.match(rf"{re.escape(date)}-s(\d+)-", r.get("shot_id", ""))] if m]
    number = max(earlier, default=0) + 1
    kind = session.get("distance_type", "carry")
    rows = []
    for i, shot in enumerate(session["shots"], start=1):
        strike = str(shot.get("strike", "")).strip().lower()
        if strike not in STRIKES:
            sys.exit(f"Shot {i}: strike must be one of {', '.join(STRIKES)}, got {shot.get('strike')!r}")
        row = {
            "shot_id": f"{date}-s{number}-{i:03d}",
            "date": date,
            "time": session.get("time", ""),
            "club": club_label(shot["club"]),
            "distance_yd": f"{float(shot['distance']):g}",
            "distance_type": shot.get("distance_type", kind),
            "strike": strike,
            "notes": shot.get("notes", ""),
        }
        for name in LAUNCH:
            row[name] = "" if shot.get(name) in (None, "") else f"{float(shot[name]):g}"
        rows.append(row)
    return rows


def stats(rows):
    """Per club: shot count, strikes, and the average/longest/shortest of non-mishits."""
    by_club = {}
    for r in rows:
        by_club.setdefault(r["club"], []).append(r)
    out = {}
    for club, shots in by_club.items():
        counted = [float(r["distance_yd"]) for r in shots if r["strike"] != "mishit"]
        out[club] = {
            "shots": len(shots),
            "good": sum(r["strike"] == "good" for r in shots),
            "ok": sum(r["strike"] == "ok" for r in shots),
            "mishit": sum(r["strike"] == "mishit" for r in shots),
            "avg": sum(counted) / len(counted) if counted else None,
            "longest": max(counted, default=None),
            "shortest": min(counted, default=None),
        }
    return out


def bag_order(clubs):
    order = list(CLUBS.values())
    return sorted(clubs, key=lambda c: (order.index(c) if c in order else len(order), c))


def summary(new_rows, history):
    now, before = stats(new_rows), stats(history)
    kind = new_rows[0]["distance_type"] if new_rows else "carry"
    lines = [f"| Club | Shots | Good / OK / Mishit | Avg {kind} | Longest | Shortest | Before |",
             "|---|---|---|---|---|---|---|"]
    fmt = lambda v: "-" if v is None else f"{v:.0f}"
    for club in bag_order(now):
        s = now[club]
        prev = before.get(club, {}).get("avg")
        change = "-" if prev is None or s["avg"] is None else f"{prev:.0f} ({s['avg'] - prev:+.0f})"
        lines.append(f"| {club} | {s['shots']} | {s['good']} / {s['ok']} / {s['mishit']} | {fmt(s['avg'])} "
                     f"| {fmt(s['longest'])} | {fmt(s['shortest'])} | {change} |")
    total = len(new_rows)
    good = sum(r["strike"] == "good" for r in new_rows)
    mishits = sum(r["strike"] == "mishit" for r in new_rows)
    lines += ["", f"{total} shots: {good} good, {total - good - mishits} ok, {mishits} mishits "
              "(mishits are left out of averages)."]
    unknown = sorted({r["club"] for r in new_rows if club_code(r["club"]) is None})
    if unknown:
        lines.append(f"Not a standard club, so clubtracker won't import it: {', '.join(unknown)}.")
    if history:
        lines.append(f"History before today: {len(history)} shots.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--session", required=True, help="JSON file describing this session's shots")
    parser.add_argument("--history", help="the player's existing range-log CSV, if they uploaded one")
    parser.add_argument("--out", required=True, help="where to write the combined CSV")
    args = parser.parse_args()

    with open(args.session) as f:
        session = json.load(f)
    history = read_csv(args.history) if args.history else []
    rows = session_rows(session, history)
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows([{c: r.get(c, "") for c in COLUMNS} for r in history] + rows)
    print(summary(rows, history))


if __name__ == "__main__":
    main()
