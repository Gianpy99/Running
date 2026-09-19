"""Athlete profile (PRD §3, §7)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .definition import Phase
from .enums import PhaseType


def _default_treadmill_warmup() -> list[Phase]:
    return [Phase(type=PhaseType.WARMUP, duration_min=10.0, speed_mph=4.0)]


def _default_treadmill_cooldown() -> list[Phase]:
    # One minute per step, walking the belt down to a stop.
    return [
        Phase(type=PhaseType.COOLDOWN, duration_min=1.0, speed_mph=mph)
        for mph in (4.5, 4.0, 3.5, 3.0, 2.5)
    ]


class Athlete(BaseModel):
    """Athlete profile and goals. Defaults reflect the PRD athlete context (§3)."""

    id: str = "athlete-1"
    age: int = 40
    height_cm: float = 180.0
    weight_kg: float | None = 86.5
    resting_hr: int | None = None
    max_hr: int | None = None
    # HR zone boundaries in bpm; if None the analytics engine estimates from max_hr.
    hr_zones: list[int] | None = None
    goal_5k_seconds: int | None = 960  # 16:00 aspirational moonshot (PRD §3, §16)
    units: str = "metric"
    timezone: str = "Europe/London"
    # Habitual treadmill structure, in the same phase DSL a session description uses.
    # Treadmill exports often record heart rate only, with no per-point distance, so these
    # phases are what lets the main set be separated from the easy ends (PRD §15).
    # Set either list empty to stop applying the default.
    treadmill_warmup: list[Phase] = Field(default_factory=_default_treadmill_warmup)
    treadmill_cooldown: list[Phase] = Field(default_factory=_default_treadmill_cooldown)

    def estimated_max_hr(self) -> int:
        """Deterministic fallback (Tanaka) used only when max_hr is unknown."""
        if self.max_hr is not None:
            return self.max_hr
        return round(208 - 0.7 * self.age)

    def zone_bounds(self) -> list[int]:
        """Five-zone lower bounds in bpm, from configured zones or estimated max HR."""
        if self.hr_zones:
            return sorted(self.hr_zones)
        hr_max = self.estimated_max_hr()
        return [round(hr_max * f) for f in (0.5, 0.6, 0.7, 0.8, 0.9)]
