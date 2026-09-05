"""Body composition measurement from the smart scale (PRD §7, §17)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BodyMeasurement(BaseModel):
    """Smart-scale reading. Bioimpedance values are noisy estimates, not clinical (§17)."""

    timestamp: datetime
    weight_kg: float
    body_fat_pct: float | None = None
    muscle_mass_kg: float | None = None
    water_pct: float | None = None
    source: str = "insmart_xls"
