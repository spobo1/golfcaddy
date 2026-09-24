"""Shot history storage and per-club distances, backed by SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from .clubs import CLUBS, DEFAULT_SKILL_LEVEL, normalize_club, normalize_skill_level, roll_fraction, typical_carry_yd
from .models import ClubDistance, ClubStats, ClubSuggestion, LaunchData, Shot

_LAUNCH = LaunchData.names()

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS players (
    user_id TEXT PRIMARY KEY,
    skill_level TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    club TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    carry_yd REAL,
    total_yd REAL,
    {", ".join(f"{name} REAL" for name in _LAUNCH)}
);
CREATE INDEX IF NOT EXISTS shots_by_user_club ON shots (user_id, club);
"""

_SHOT_COLUMNS = ["id", "user_id", "club", "recorded_at", "carry_yd", "total_yd", *_LAUNCH]


class ClubTracker:
    """Records how far each player hits each club.

    ``db_path`` is a SQLite file; the default keeps everything in memory.
    """

    def __init__(self, db_path: str = ":memory:"):
        self._db = sqlite3.connect(db_path)
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # Players

    def set_skill_level(self, user_id: str, skill_level: str) -> None:
        """Set a player's skill level: beginner, intermediate, advanced or expert."""
        level = normalize_skill_level(skill_level)
        with self._db:
            self._db.execute(
                "INSERT INTO players (user_id, skill_level) VALUES (?, ?) "
                "ON CONFLICT (user_id) DO UPDATE SET skill_level = excluded.skill_level",
                (user_id, level),
            )

    def skill_level(self, user_id: str) -> str:
        """The player's skill level, or DEFAULT_SKILL_LEVEL if it hasn't been set."""
        row = self._db.execute("SELECT skill_level FROM players WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else DEFAULT_SKILL_LEVEL

    # Shots

    def record_shot(
        self,
        user_id: str,
        club: str,
        carry_yd: Optional[float] = None,
        total_yd: Optional[float] = None,
        launch: Optional[LaunchData] = None,
        recorded_at: Optional[datetime] = None,
    ) -> Shot:
        """Save a shot. Needs a carry, a total distance, or both.

        ``recorded_at`` defaults to now; a time without a time zone is taken
        as local time. Times are stored in UTC.
        """
        if carry_yd is None and total_yd is None:
            raise ValueError("A shot needs a carry_yd, a total_yd, or both")
        for name, value in (("carry_yd", carry_yd), ("total_yd", total_yd)):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")
        shot = Shot(
            id=0,
            user_id=user_id,
            club=normalize_club(club),
            recorded_at=(recorded_at or datetime.now()).astimezone(timezone.utc),
            carry_yd=carry_yd,
            total_yd=total_yd,
            launch=launch or LaunchData(),
        )
        values = [shot.user_id, shot.club, shot.recorded_at.isoformat(), carry_yd, total_yd]
        values += [getattr(shot.launch, name) for name in _LAUNCH]
        with self._db:
            cursor = self._db.execute(
                f"INSERT INTO shots ({', '.join(_SHOT_COLUMNS[1:])}) VALUES ({', '.join('?' * len(values))})",
                values,
            )
        shot.id = cursor.lastrowid
        return shot

    def delete_shot(self, shot_id: int) -> bool:
        """Remove a shot, e.g. one entered by mistake. Returns whether it existed."""
        with self._db:
            return self._db.execute("DELETE FROM shots WHERE id = ?", (shot_id,)).rowcount > 0

    def shots(self, user_id: str, club: Optional[str] = None, limit: Optional[int] = None) -> list[Shot]:
        """A player's shot history, newest first, optionally for one club."""
        sql = f"SELECT {', '.join(_SHOT_COLUMNS)} FROM shots WHERE user_id = ?"
        params: list = [user_id]
        if club is not None:
            sql += " AND club = ?"
            params.append(normalize_club(club))
        sql += " ORDER BY recorded_at DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_shot_from_row(row) for row in self._db.execute(sql, params)]

    # Distances

    def club_averages(self, user_id: str) -> dict[str, ClubStats]:
        """Averages for every club the player has hit, in bag order."""
        rows = self._db.execute(
            f"SELECT club, COUNT(*), AVG(carry_yd), AVG(total_yd), {', '.join(f'AVG({n})' for n in _LAUNCH)} "
            "FROM shots WHERE user_id = ? GROUP BY club",
            (user_id,),
        ).fetchall()
        stats = {
            row[0]: ClubStats(
                club=row[0],
                shots=row[1],
                carry_yd=_round(row[2]),
                total_yd=_round(row[3]),
                launch=LaunchData(**{name: _round(v) for name, v in zip(_LAUNCH, row[4:])}),
            )
            for row in rows
        }
        return {club: stats[club] for club in CLUBS if club in stats}

    def club_distance(self, user_id: str, club: str) -> ClubDistance:
        """How far the player hits a club.

        Uses the player's average when they have shots with the club,
        otherwise typical distances for their skill level, scaled by how far
        the player hits the clubs they do have history with compared with
        typical. A missing carry or total is worked out from the other using
        typical roll.
        """
        club = normalize_club(club)
        return next(d for d in self.bag(user_id) if d.club == club)

    def bag(self, user_id: str) -> list[ClubDistance]:
        """Distances for every club, longest club first."""
        averages, level = self.club_averages(user_id), self.skill_level(user_id)
        history = {club: _from_history(club, stats) for club, stats in averages.items()}
        # How the player's distances compare with typical for their level.
        ratios = [d.carry_yd / typical_carry_yd(club, level) for club, d in history.items()]
        scale = round(sum(ratios) / len(ratios), 3) if ratios else 1.0
        return [history.get(club) or _estimate(club, level, scale) for club in CLUBS]

    def suggest_club(
        self,
        user_id: str,
        distance_yd: float,
        clubs: Optional[Iterable[str]] = None,
        include_driver: bool = False,
    ) -> ClubSuggestion:
        """The club whose total distance (carry plus roll) is closest to ``distance_yd``.

        Meant for the distance to the centre of the green. Uses the player's
        averages where they have them and skill-level estimates elsewhere.
        ``clubs`` limits the choice to the clubs the player carries. The
        driver is left out unless ``include_driver`` is set, since it is
        rarely hit into a green. When two clubs are equally close, the longer
        one is suggested, since most players miss short.
        """
        if distance_yd <= 0:
            raise ValueError(f"distance_yd must be positive, got {distance_yd}")
        allowed = {normalize_club(c) for c in clubs} if clubs is not None else set(CLUBS)
        if not include_driver:
            allowed.discard("driver")
        if not allowed:
            raise ValueError("No clubs to choose from")
        # Longest first, so ties go to the longer club.
        options = sorted((d for d in self.bag(user_id) if d.club in allowed), key=lambda d: -d.total_yd)
        best = min(range(len(options)), key=lambda i: abs(options[i].total_yd - distance_yd))
        chosen = options[best]
        return ClubSuggestion(
            club=chosen.club,
            distance=chosen,
            target_yd=distance_yd,
            difference_yd=round(chosen.total_yd - distance_yd, 1),
            longer=options[best - 1] if best > 0 else None,
            shorter=options[best + 1] if best + 1 < len(options) else None,
        )


def _estimate(club: str, skill_level: str, scale: float) -> ClubDistance:
    carry = _round(typical_carry_yd(club, skill_level) * scale)
    total = _round(carry * (1 + roll_fraction(club)))
    return ClubDistance(club, carry, total, "estimate", skill_level=skill_level, scale=scale)


def _from_history(club: str, stats: ClubStats) -> ClubDistance:
    roll = roll_fraction(club)
    carry = stats.carry_yd if stats.carry_yd is not None else _round(stats.total_yd / (1 + roll))
    total = stats.total_yd if stats.total_yd is not None else _round(stats.carry_yd * (1 + roll))
    return ClubDistance(club, carry, total, "history", shots=stats.shots)


def _shot_from_row(row) -> Shot:
    values = dict(zip(_SHOT_COLUMNS, row))
    return Shot(
        id=values["id"],
        user_id=values["user_id"],
        club=values["club"],
        recorded_at=datetime.fromisoformat(values["recorded_at"]),
        carry_yd=values["carry_yd"],
        total_yd=values["total_yd"],
        launch=LaunchData(**{name: values[name] for name in _LAUNCH}),
    )


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 1)
