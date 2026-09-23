# golfcaddy
Repository created via GitHub Copilot task

## coursemapper

Given a golf course name, `coursemapper` returns the GPS coordinates of every
hole's tee boxes and the centre of its green, using OpenStreetMap data
(Nominatim to find the course, Overpass for `golf=hole`, `golf=tee` and
`golf=green` features). Standard library only; Python 3.10+.

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

- **Tee boxes**: each mapped `golf=tee` feature (its centroid) is assigned to
  the hole whose line starts closest to it, within 150 m. Tees are sorted back
  to front and include the straight-line distance to the green centre.
- **Green centre**: centroid of the `golf=green` polygon nearest the end of the
  hole line, within 75 m. Double greens shared by several holes use each hole
  line's end point instead.
- If a course has no tee or green mapped for a hole, the start/end of the hole
  line is used and the result is marked `source="hole_line"` /
  `green_source="hole_line"`.

Results are only as good as the course's OpenStreetMap mapping.

Run the tests with `python -m unittest discover`.
