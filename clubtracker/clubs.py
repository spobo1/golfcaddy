"""The clubs in a bag and typical distances for each skill level."""

from __future__ import annotations

import re

# Canonical club codes, longest to shortest.
CLUBS = (
    "driver", "3w", "5w", "7w",
    "3h", "4h", "5h",
    "3i", "4i", "5i", "6i", "7i", "8i", "9i",
    "pw", "gw", "sw", "lw",
)

SKILL_LEVELS = ("beginner", "intermediate", "advanced", "expert")

# Used when a user's skill level hasn't been set.
DEFAULT_SKILL_LEVEL = "intermediate"

# Approximate carry distances in yards for each skill level, in the order of
# SKILL_LEVELS. These are rough typical figures for adult players, meant as a
# starting point until a player has their own history.
TYPICAL_CARRY_YD = {
    "driver": (175, 205, 230, 255),
    "3w": (160, 185, 210, 235),
    "5w": (150, 175, 195, 220),
    "7w": (145, 170, 190, 210),
    "3h": (150, 175, 195, 215),
    "4h": (145, 170, 190, 205),
    "5h": (140, 160, 180, 195),
    "3i": (140, 165, 185, 205),
    "4i": (135, 160, 180, 200),
    "5i": (130, 150, 170, 190),
    "6i": (120, 140, 160, 180),
    "7i": (110, 130, 150, 170),
    "8i": (100, 120, 140, 160),
    "9i": (90, 110, 130, 145),
    "pw": (80, 100, 120, 135),
    "gw": (70, 90, 105, 120),
    "sw": (60, 75, 90, 105),
    "lw": (45, 60, 75, 85),
}

# Roll after landing, as a fraction of carry, used to turn a carry into a
# total distance (and back) when only one of them is known.
_ROLL = {"driver": 0.08, "w": 0.06, "h": 0.05, "long_iron": 0.04, "mid_iron": 0.03, "short_iron": 0.02, "wedge": 0.01}


def roll_fraction(club: str) -> float:
    if club == "driver":
        return _ROLL["driver"]
    if club.endswith("w") and club[0].isdigit():
        return _ROLL["w"]
    if club.endswith("h"):
        return _ROLL["h"]
    if club.endswith("i"):
        number = int(club[:-1])
        return _ROLL["long_iron"] if number <= 4 else _ROLL["mid_iron"] if number <= 7 else _ROLL["short_iron"]
    return _ROLL["wedge"]


def typical_carry_yd(club: str, skill_level: str) -> float:
    return float(TYPICAL_CARRY_YD[club][SKILL_LEVELS.index(skill_level)])


_ALIASES = {
    "d": "driver", "dr": "driver", "1w": "driver",
    "p": "pw", "pitchingwedge": "pw", "pitching": "pw",
    "g": "gw", "gapwedge": "gw", "gap": "gw", "aw": "gw", "approachwedge": "gw",
    "s": "sw", "sandwedge": "sw", "sand": "sw",
    "l": "lw", "lobwedge": "lw", "lob": "lw",
}
_KIND = {"wood": "w", "w": "w", "hybrid": "h", "hy": "h", "h": "h", "rescue": "h", "iron": "i", "i": "i"}


def normalize_club(name: str) -> str:
    """Turn a club name like "7 iron", "7-Iron", "3 wood" or "PW" into its code.

    Raises ValueError for anything that isn't a club in CLUBS.
    """
    key = re.sub(r"[\s\-_]", "", name.strip().lower())
    if key in CLUBS:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    match = re.fullmatch(r"(\d+)([a-z]+)", key)
    if match and match.group(2) in _KIND:
        code = match.group(1) + _KIND[match.group(2)]
        if code in CLUBS:
            return code
    raise ValueError(f"Unknown club {name!r}; expected one of {', '.join(CLUBS)}")


def normalize_skill_level(level: str) -> str:
    key = level.strip().lower()
    if key not in SKILL_LEVELS:
        raise ValueError(f"Unknown skill level {level!r}; expected one of {', '.join(SKILL_LEVELS)}")
    return key
