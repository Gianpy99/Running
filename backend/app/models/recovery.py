"""Athlete-reported recovery context (PRD §7, §10)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class RecoveryContext(BaseModel):
    """Subjective / recovery context. All fields are athlete-reported inputs (§27)."""

    for_date: date
    sleep_hours: float | None = None
    sleep_score: int | None = None
    resting_hr: int | None = None
    subjective_energy: int | None = Field(default=None, ge=1, le=5)
    leg_fatigue: int | None = Field(default=None, ge=1, le=5)
    gi_discomfort: bool = False
    illness: bool = False
    # Pain reported as localized/sharp/persistent — a safety-relevant flag (§18).
    concerning_pain: bool = False
    notes: str | None = None
