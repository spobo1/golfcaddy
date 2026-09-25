"""Data types used by clubtracker. Distances are in yards, angles in degrees."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Optional


@dataclass
class LaunchData:
    """Optional readings from a launch monitor. Leave out whatever isn't measured.

    Horizontal angles and offline distance are positive to the right of the
    target line.
    """

    ball_speed_mph: Optional[float] = None
    club_speed_mph: Optional[float] = None
    smash_factor: Optional[float] = None
    # Vertical angle the ball leaves the face at.
    launch_angle_deg: Optional[float] = None
    # Horizontal start direction.
    launch_direction_deg: Optional[float] = None
    spin_rate_rpm: Optional[float] = None
    spin_axis_deg: Optional[float] = None
    attack_angle_deg: Optional[float] = None
    club_path_deg: Optional[float] = None
    face_angle_deg: Optional[float] = None
    apex_yd: Optional[float] = None
    descent_angle_deg: Optional[float] = None
    offline_yd: Optional[float] = None

    @classmethod
    def names(cls) -> list[str]:
        return [f.name for f in fields(cls)]


@dataclass
class Shot:
    id: int
    user_id: str
    club: str
    recorded_at: datetime
    carry_yd: Optional[float] = None
    total_yd: Optional[float] = None
    launch: LaunchData = field(default_factory=LaunchData)
    # "good", "ok" or "mishit", when known. Mishits are left out of averages.
    strike: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["recorded_at"] = self.recorded_at.isoformat()
        return d


@dataclass
class ClubStats:
    """A club's averages over a player's shot history, leaving out mishits."""

    club: str
    shots: int
    # None when no shot with that club recorded a carry (or total).
    carry_yd: Optional[float]
    total_yd: Optional[float]
    # Averages of each launch monitor reading, over the shots that have it.
    launch: LaunchData
    # Mishits with this club, which ``shots`` and the averages leave out.
    mishits: int = 0


@dataclass
class ClubDistance:
    """How far a player hits a club."""

    club: str
    carry_yd: float
    total_yd: float
    # "history" when averaged from the player's shots, or "estimate" when
    # taken from typical distances for their skill level.
    source: str
    shots: int = 0
    # The skill level an estimate was based on.
    skill_level: Optional[str] = None
    # What an estimate's typical distance was multiplied by: how far the
    # player hits their other clubs compared with typical (1.0 with no history).
    scale: float = 1.0


@dataclass
class ClubSuggestion:
    """The club to hit for a distance, with the clubs either side of it."""

    club: str
    distance: ClubDistance
    target_yd: float
    # Where the suggested club is expected to finish relative to the target:
    # positive is long, negative is short.
    difference_yd: float
    # The next club that goes further and the next that goes shorter, if any.
    longer: Optional[ClubDistance] = None
    shorter: Optional[ClubDistance] = None
