"""The practice-log CSV written by the range-practice skill, and importing it.

One row per shot:

    shot_id        unique id, e.g. 2026-09-25-s1-007 (date, session, shot)
    date, time     when the session happened (local time; time may be blank)
    club           the club as the player named it, e.g. "7 iron"
    distance_yd    how far it went
    distance_type  "carry" or "total"
    strike         "good", "ok" or "mishit"
    notes          anything else the player said about the shot
    ...            optional launch monitor readings, named as in LaunchData
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .clubs import normalize_club
from .models import LaunchData

if TYPE_CHECKING:
    from .tracker import ClubTracker

COLUMNS = ["shot_id", "date", "time", "club", "distance_yd", "distance_type", "strike", "notes", *LaunchData.names()]


@dataclass
class ImportResult:
    added: int = 0
    # Shots already in the database from an earlier import of the same file.
    already_imported: int = 0
    # Rows that couldn't be used, with why, e.g. a club clubtracker doesn't track.
    skipped: list[str] = None

    def __post_init__(self):
        self.skipped = self.skipped or []


def import_range_csv(tracker: "ClubTracker", user_id: str, path: str) -> ImportResult:
    """Add the shots in a practice-log CSV to the player's history."""
    result = ImportResult()
    with open(path, newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            label = f"line {n} ({row.get('club') or 'no club'})"
            try:
                club = normalize_club(row.get("club") or "")
                distance = float(row["distance_yd"])
            except (ValueError, KeyError, TypeError) as e:
                result.skipped.append(f"{label}: {e}")
                continue
            kind = (row.get("distance_type") or "carry").strip().lower()
            when = datetime.fromisoformat(f"{row['date']}T{(row.get('time') or '12:00').strip()}")
            launch = LaunchData(**{
                name: float(row[name]) for name in LaunchData.names() if (row.get(name) or "").strip()
            })
            try:
                tracker.record_shot(
                    user_id, club,
                    carry_yd=distance if kind == "carry" else None,
                    total_yd=distance if kind == "total" else None,
                    launch=launch,
                    recorded_at=when,
                    strike=(row.get("strike") or "").strip() or None,
                    source_id=(row.get("shot_id") or "").strip() or None,
                )
            except sqlite3.IntegrityError:
                result.already_imported += 1
            except ValueError as e:
                result.skipped.append(f"{label}: {e}")
            else:
                result.added += 1
    return result
