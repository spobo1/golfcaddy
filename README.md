# golfcaddy
Repository created via GitHub Copilot task

## coursemapper

Given a golf course name, `coursemapper` returns the GPS coordinates of every
hole's tee boxes and the centre of its green, plus its bunkers and water, using OpenStreetMap data
(Nominatim to find the course, Overpass for `golf=hole`, `golf=tee` and
`golf=green` features). If Overpass can't be reached it falls back to the main
OpenStreetMap API, which is meant for occasional, low-volume reads. Standard
library only; Python 3.10+.

```sh
python -m coursemapper "Pebble Beach Golf Links"
```

```python
from coursemapper import map_course

course = map_course("Pebble Beach Golf Links")
for hole in course.holes:
    print(hole.number, hole.par, hole.green_center, [t.location for t in hole.tees])
```

How positions are worked out:

- **Course**: the first Nominatim result that is a golf course. If the name
  only matches something else (e.g. the clubhouse), the golf course within
  2 km that shares the most distinctive name words (ignoring words like
  "golf", "links", "course" and "club"), else the nearest one.
- **Tee boxes**: each mapped `golf=tee` feature (its centroid) is assigned to
  the hole whose line starts closest to it, within 150 m, or to the nearest
  hole with the tee's `ref` number when it has one. Hole lines usually start
  at the back tee, so a tee more than 25 m farther from the green than the
  hole is long goes to another nearby hole if one fits; otherwise it stays
  with the nearest hole (some courses draw lines from a middle tee). Tees are
  sorted back to front and
  include the straight-line distance to the green centre.
- **Green centre**: centroid of the `golf=green` polygon nearest the end of the
  hole line, within 75 m. Double greens shared by several holes use each hole
  line's end point instead.
- **Front and back of the green**: where the line of approach through the
  green centre crosses the green's outline. The approach direction comes from
  the last 100 m of the hole line, so doglegs are measured the way the green
  is actually played. Each tee also gets its distance to the front and back.
- **Fairways**: each `golf=fairway` outline goes to the hole whose line passes
  closest to its centre (within 60 m). Split fairways give a hole several.
- **Hazards**: bunkers (`golf=bunker`), water hazards (`golf=water_hazard`,
  `golf=lateral_water_hazard`) and other water (`natural=water`, unless it
  duplicates a mapped water hazard). OpenStreetMap doesn't say which hole a
  hazard belongs to, so a bunker goes to the nearest hole whose line comes
  within 50 m of it, and water goes to every hole that passes within 50 m.
  Each hazard reports its side of the line of play (`left`, `right` or
  `crossing`), the distance from the back tee to reach it and to carry it,
  its distance to the green centre, and its outline.
- If a course has no tee or green mapped for a hole, the start/end of the hole
  line is used and the result is marked `source="hole_line"` /
  `green_source="hole_line"`.

### Tee colours from a scorecard

OpenStreetMap rarely says which tee box is which colour. Pass a scorecard to
label them:

```sh
python -m coursemapper "Sterling Farms Golf Course, Stamford, CT" --scorecard scorecards/sterling_farms.json
```

A scorecard file lists each colour's yardage for holes 1–18 (see
`scorecards/`). On each hole the longest set goes on the rearmost mapped box,
and every other colour on the box whose distance forward of it best matches how
much shorter that colour plays. Each tee box then lists its `colours`. Where
fewer boxes are mapped than there are tee sets, several colours share a box.

Each hole also reports `length_m`, its length along the mapped hole line.

Results are only as good as the course's OpenStreetMap mapping. Holes of
every course inside the boundary are returned, so a club with a separate short
course inside the same boundary (e.g. Augusta National's Par 3 Course) returns
two sets of hole numbers.

Run the tests with `python -m unittest discover`.

## clubtracker

Keeps track of how far each player hits each club. Every shot is saved with
optional launch monitor readings, averages are kept per club, and clubs a
player hasn't hit yet get typical distances for their skill level. History is
stored in SQLite (standard library); distances are in yards, angles in degrees.

```python
from clubtracker import ClubTracker, LaunchData

tracker = ClubTracker("shots.db")          # or ClubTracker() for in-memory
tracker.set_skill_level("ann", "intermediate")

tracker.record_shot("ann", "7 iron", carry_yd=148, total_yd=153)
tracker.record_shot(
    "ann", "driver", carry_yd=232, total_yd=251,
    launch=LaunchData(launch_angle_deg=13.1, ball_speed_mph=148, spin_rate_rpm=2750),
)

tracker.shots("ann", club="7i")            # history, newest first
tracker.club_averages("ann")               # per-club averages, incl. launch data
tracker.club_distance("ann", "7i")         # source="history": Ann's average
tracker.club_distance("ann", "pw")         # source="estimate": typical intermediate PW
tracker.bag("ann")                          # every club, longest first

s = tracker.suggest_club("ann", 155)       # club for 155 yd to the green
s.club, s.difference_yd                    # e.g. "6i", +4.0 (finishes 4 yd long)
s.longer.club, s.shorter.club              # the clubs either side
```

- **Clubs**: driver, 3/5/7 woods, 3–5 hybrids, 3–9 irons and PW/GW/SW/LW.
  Names like "7 iron", "7-Iron", "3 wood" or "sand wedge" are accepted.
- **Shots** need a carry, a total, or both. Launch monitor readings
  (`LaunchData`) are all optional: ball and club speed, smash factor, launch
  angle and direction, spin rate and axis, attack angle, club path, face angle,
  apex, descent angle and offline distance.
- **Distances**: a club's distance is the player's average once they have a
  shot with it. Otherwise it's an estimate from typical carries for their
  skill level (`beginner`, `intermediate`, `advanced`, `expert`; players
  without one set are treated as `intermediate`), scaled by how far the player
  hits the clubs they do have history with compared with typical. When only carry or only
  total is known, the other is worked out from typical roll for the club.
- `delete_shot(id)` removes a shot entered by mistake.
- **Club suggestions**: `suggest_club(user, distance_yd)` picks the club whose
  total distance (carry plus roll) finishes closest to the target, usually the
  green centre, and returns the next club up and down with it. Ties go to the
  longer club, as most players miss short. `clubs=[...]` limits the choice to
  what's in the player's bag; the driver is left out unless
  `include_driver=True`. Beyond the longest club, it returns that club with a
  negative `difference_yd`.

## caddy

Club advice for the shot in front of the player, combining a hole from
`coursemapper` (green front, centre and back, and its hazards) with the
player's distances from `clubtracker`.

```python
from caddy import advise_shot, tee_position
from clubtracker import ClubTracker
from coursemapper import map_course

course = map_course("Sterling Farms Golf Course, Stamford, CT")
hole = next(h for h in course.holes if h.number == 17)
tracker = ClubTracker("shots.db")

advice = advise_shot(tracker, "ann", hole, tee_position(hole))   # or any GPS Coordinate
advice.club, advice.reason   # "4i", "Take 4 iron to carry the bunker (148 to carry, 4 iron carries 160)."
advice.to_front_yd, advice.to_center_yd, advice.to_back_yd
advice.hazards               # bunkers and water along or beside the line, with reach and carry
```

Or from the command line:

```sh
python -m caddy "Sterling Farms Golf Course, Stamford, CT" --hole 17 --user ann --db shots.db \
    --scorecard scorecards/sterling_farms.json --tee White
```

- **Hazards ahead**: bunkers and water that the line to the green centre runs
  through or passes within 10 yd of are "in the way", with the yardage to
  reach and to carry them. Ones up to 30 yd to the side are listed as `left`
  or `right`. Hazards behind the player or more than 30 yd past the green are
  ignored.
- **Choosing a club**: of the clubs that won't land in, or roll into and stop
  in, a hazard in the way (with 5 yd of leeway), the one finishing closest to
  the green centre, with yards past the back of the green counting double. So
  it takes more club to carry a hazard when that works (`plan="carry"`), plays
  to the front of the green when a hazard cuts in past the centre
  (`plan="front"`), and lays up short of a hazard before the green when it
  can't be carried (`plan="layup"`). If every club is at
  risk, it picks the one closest to the green (`plan="no_safe_club"`).
- **Driver** is only considered when the green is out of reach of every other
  club, unless `include_driver` says otherwise. `clubs=[...]` limits the choice
  to the player's bag.
- Distances are straight lines. Wind, elevation and lie aren't taken into
  account.
