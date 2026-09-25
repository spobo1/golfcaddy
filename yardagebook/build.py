"""Build a course's yardage book and caddy page.

Maps the course (coursemapper), labels tees from its scorecard, works out
caddy advice for every hole, tee colour and skill level (caddy), downloads
an aerial photo from the USGS National Map, and writes a self-contained HTML
page plus the photo next to it.
"""

from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request

from caddy import advise_shot, tee_position
from clubtracker import SKILL_LEVELS, ClubTracker
from coursemapper import apply_scorecard, load_scorecard, map_course
from coursemapper.models import CourseMap
from coursemapper.osm import USER_AGENT

YARDS_PER_METRE = 1.0936133
TEMPLATE = os.path.join(os.path.dirname(__file__), "template.html")

# Public-domain USDA/USGS aerial imagery (US only).
AERIAL_URL = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
AERIAL_PADDING_M = 70
AERIAL_MAX_PX = 2000

_HAZARD_CODE = {"bunker": "b", "water": "w", "lateral_water": "l"}


def build_page(
    query: str,
    scorecard_path: str,
    out_path: str,
    title: str,
    place: str,
    default_tee: str,
    aerial: bool = True,
) -> dict:
    """Write the page to ``out_path`` (and its aerial photo alongside). Returns a summary."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    course = map_course(query)
    apply_scorecard(course, load_scorecard(scorecard_path))
    with open(scorecard_path) as f:
        card = json.load(f)

    holes, hazards = _holes_and_hazards(course)
    data = {
        "name": course.name,
        "osm": f"{course.osm_type}/{course.osm_id}",
        "holes": holes,
        "hazards": hazards,
        "card": card["tees"],
        "cardSource": card["source"],
        "cardSourceName": card.get("source_name", "the scorecard on mScorecard"),
        "defaultTee": default_tee,
        "advice": _advice(course, list(card["tees"])),
    }
    if aerial:
        data["aerial"] = _download_aerial(holes, hazards, out_path)

    with open(TEMPLATE) as f:
        template = f.read()
    html = (
        template.replace("__TITLE__", title)
        .replace("__PLACE__", place)
        .replace("__NAME__", course.name)
        .replace("__DATA__", json.dumps(data, separators=(",", ":")))
    )
    with open(out_path, "w") as f:
        f.write(html)
    return {"course": course.name, "holes": len(holes), "hazards": len(hazards), "page": out_path,
            "aerial": data.get("aerial", {}).get("src")}


def _holes_and_hazards(course: CourseMap) -> tuple[list[dict], list[dict]]:
    """Compact per-hole data for the page, with hazards shared between holes listed once."""
    def ll(c):
        return [round(c.lat, 6), round(c.lon, 6)] if c else None

    def yd(m):
        return round(m * YARDS_PER_METRE)

    hazards, index, holes = [], {}, []
    for h in course.holes:
        zs = []
        for z in h.hazards:
            key = (z.kind, round(z.center.lat, 6), round(z.center.lon, 6))
            if key not in index:
                index[key] = len(hazards)
                hazards.append({"k": _HAZARD_CODE[z.kind], "o": [ll(p) for p in z.outline]})
            zs.append([index[key], z.side[0], yd(z.reach_from_back_tee_m), yd(z.carry_from_back_tee_m)])
        tees = [
            [*ll(t.location), yd(t.distance_to_green_m),
             yd(t.distance_to_green_front_m or t.distance_to_green_m),
             yd(t.distance_to_green_back_m or t.distance_to_green_m), t.colours]
            for t in h.tees
        ]
        holes.append({"n": h.number, "par": h.par, "g": ll(h.green_center), "f": ll(h.green_front),
                      "b": ll(h.green_back), "t": tees, "z": zs, "fw": [[ll(p) for p in o] for o in h.fairways]})
    return holes, hazards


def _advice(course: CourseMap, colours: list[str]) -> dict:
    """Caddy advice from each tee colour for each skill level, using typical distances."""
    tracker = ClubTracker()
    for level in SKILL_LEVELS:
        tracker.set_skill_level(level, level)
    result = {}
    for h in course.holes:
        result[h.number] = {}
        for level in SKILL_LEVELS:
            result[h.number][level] = {}
            for colour in colours:
                a = advise_shot(tracker, level, h, tee_position(h, colour))
                result[h.number][level][colour] = [
                    a.club, a.plan, a.reason, round(a.to_front_yd or a.to_center_yd),
                    round(a.to_center_yd), round(a.to_back_yd or a.to_center_yd),
                ]
    tracker.close()
    return result


def _download_aerial(holes: list[dict], hazards: list[dict], out_path: str) -> dict:
    """Fetch an aerial photo covering the course, in plain lat/lon so it lines up with the page's map.

    The page places the photo using the extent the service reports back.
    """
    pts = [p for h in holes for p in [h["g"], *[t[:2] for t in h["t"]], *[q for o in h["fw"] for q in o]]]
    pts += [p for z in hazards for p in z["o"]]
    lat0 = sum(p[0] for p in pts) / len(pts)
    pad_lat = AERIAL_PADDING_M / 111_320
    pad_lon = pad_lat / math.cos(math.radians(lat0))
    xmin, xmax = min(p[1] for p in pts) - pad_lon, max(p[1] for p in pts) + pad_lon
    ymin, ymax = min(p[0] for p in pts) - pad_lat, max(p[0] for p in pts) + pad_lat
    width_m = (xmax - xmin) * 111_320 * math.cos(math.radians(lat0))
    height_m = (ymax - ymin) * 111_320
    # About 1 m per pixel, capped in size.
    metres_per_px = max(1.0, max(width_m, height_m) / AERIAL_MAX_PX)
    query = urllib.parse.urlencode({
        "bbox": f"{xmin},{ymin},{xmax},{ymax}", "bboxSR": 4326, "imageSR": 4326,
        "size": f"{round(width_m / metres_per_px)},{round(height_m / metres_per_px)}",
        "format": "jpg", "f": "json",
    })
    meta = _get_json(f"{AERIAL_URL}?{query}")
    src = os.path.splitext(os.path.basename(out_path))[0] + "-aerial.jpg"
    req = urllib.request.Request(meta["href"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as resp, open(os.path.join(os.path.dirname(os.path.abspath(out_path)), src), "wb") as f:
        f.write(resp.read())
    e = meta["extent"]
    return {"src": src, "extent": [e["ymin"], e["xmin"], e["ymax"], e["xmax"]], "size": [meta["width"], meta["height"]]}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.load(resp)
