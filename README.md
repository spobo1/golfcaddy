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

Each hole also reports `length_m`, its length along the mapped hole line.

Results are only as good as the course's OpenStreetMap mapping. Holes of
every course inside the boundary are returned, so a club with a separate short
course inside the same boundary (e.g. Augusta National's Par 3 Course) returns
two sets of hole numbers.

Run the tests with `python -m unittest discover`.
