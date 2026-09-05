"""Canonical workout (PRD §7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import CompletionStatus, SessionType, TerrainType
from .trackpoint import Trackpoint


class Workout(BaseModel):
    """A single session. `source_file` traces back to the authoritative raw file."""

    id: str
    source: str = "tcx"
    source_file: str | None = None
    sport: str = "Running"
    start_time: datetime
    duration_s: float = 0.0
    distance_m: float = 0.0
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    avg_hr: int | None = None
    avg_pace_s_per_km: float | None = None
    session_type: SessionType = SessionType.UNCLASSIFIED
    terrain: TerrainType = TerrainType.UNKNOWN
    completion: CompletionStatus = CompletionStatus.UNKNOWN
    notes: str | None = None
    # Manually entered treadmill metadata (PRD §15) — user-reported, not measured.
    treadmill_speed_mph: float | None = None
    treadmill_incline_pct: float | None = None
    trackpoints: list[Trackpoint] = Field(default_factory=list)

    def duration_hms(self) -> str:
        s = int(self.duration_s)
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
