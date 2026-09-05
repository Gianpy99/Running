"""Athlete profile (PRD §3, §7)."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
