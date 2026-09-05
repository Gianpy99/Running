"""Workout DSL definition (PRD §8, §7)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import PhaseType


class AdaptiveRule(BaseModel):
    """A deterministic adaptation rule for a phase (PRD §5.3, §11).

    `action` is one of: reduce, extend, downgrade. Rules are evaluated locally; the
    LLM never performs the threshold comparison (PRD §12).
    """

    when: str  # human-readable condition label, e.g. "hr_above_target"
    action: str  # reduce | extend | downgrade
    detail: str | None = None


class Phase(BaseModel):
    """A single workout phase. Speed/incline are treadmill targets (PRD §8, §15)."""

    type: PhaseType
    duration_min: float | None = None
    distance_m: float | None = None
    speed_mph: float | None = None
    incline_pct: float | None = None
    hr_target: tuple[int, int] | None = None
    rpe_target: int | None = None
    tolerance_bpm: int = 8
    adaptive_rules: list[AdaptiveRule] = Field(default_factory=list)


class WorkoutDefinition(BaseModel):
    """A structured, replayable workout (PRD §8)."""

    name: str
    phases: list[Phase]

    @property
    def total_duration_min(self) -> float:
        return sum(p.duration_min or 0.0 for p in self.phases)
