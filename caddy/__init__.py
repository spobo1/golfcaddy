"""caddy: club advice for the shot in front of the player.

Brings together a hole's green and hazards (coursemapper) and how far the
player hits each club (clubtracker).
"""

from .advice import HazardAhead, ShotAdvice, advise_shot, hazards_ahead, tee_position

__all__ = ["HazardAhead", "ShotAdvice", "advise_shot", "hazards_ahead", "tee_position"]
