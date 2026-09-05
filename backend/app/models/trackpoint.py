"""Canonical trackpoint (PRD §7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import QualityFlag


class Trackpoint(BaseModel):
    """A single sample. Raw values are preserved; quality flags never mutate them."""

    timestamp: datetime
    elapsed_s: float = 0.0
    distance_m: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None
    speed_mps: float | None = None
    hr_bpm: int | None = None
    cadence_spm: int | None = None
    quality: list[QualityFlag] = Field(default_factory=lambda: [QualityFlag.OK])

    @property
    def pace_s_per_km(self) -> float | None:
        """Pace derived from speed; None when stopped or speed unavailable."""
        if self.speed_mps is None or self.speed_mps <= 0.05:
            return None
        return 1000.0 / self.speed_mps

    @property
    def is_hr_suspect(self) -> bool:
        return any(f != QualityFlag.OK and f.name.startswith("HR") for f in self.quality)
