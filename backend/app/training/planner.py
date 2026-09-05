"""Deterministic planning helpers (PRD §5.3, §10, §26).

Adapts a workout definition given a readiness decision, and proposes a simple next
session. These are deterministic rules; AI proposals (PRD §12) must be validated through
these same structures before execution.
"""

from __future__ import annotations

from ..models import Phase, WorkoutDefinition
from ..models.enums import PhaseType, ReadinessLevel
from ..services.readiness import ReadinessResult
from .dsl import standard_treadmill_session


def adapt_definition(definition: WorkoutDefinition, readiness: ReadinessResult) -> WorkoutDefinition:
    """Reduce/downgrade a session based on readiness (PRD §10, §26).

    - GREEN: unchanged.
    - AMBER: reduce hard/progression/interval phase durations by ~30%.
    - RED: downgrade to an easy aerobic session.
    """
    if readiness.level == ReadinessLevel.GREEN:
        return definition

    if readiness.level == ReadinessLevel.RED:
        return WorkoutDefinition(
            name=f"{definition.name} (downgraded: easy aerobic)",
            phases=[
                Phase(type=PhaseType.WARMUP, duration_min=10, speed_mph=4.0, incline_pct=1),
                Phase(type=PhaseType.AEROBIC, duration_min=20, speed_mph=4.5, incline_pct=1,
                      hr_target=(125, 140)),
                Phase(type=PhaseType.COOLDOWN, duration_min=5, speed_mph=3.5, incline_pct=0),
            ],
        )

    # AMBER: trim intensity.
    new_phases: list[Phase] = []
    for p in definition.phases:
        if p.type in (PhaseType.PROGRESSION, PhaseType.INTERVAL) and p.duration_min:
            new_phases.append(p.model_copy(update={"duration_min": round(p.duration_min * 0.7, 1)}))
        else:
            new_phases.append(p)
    return WorkoutDefinition(name=f"{definition.name} (reduced)", phases=new_phases)


def generate_next_session(readiness: ReadinessResult, base: WorkoutDefinition | None = None) -> WorkoutDefinition:
    """Propose the next session from readiness (deterministic v0)."""
    base = base or standard_treadmill_session()
    return adapt_definition(base, readiness)
