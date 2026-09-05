"""Workout DSL loading and the standard treadmill protocol (PRD §8, §15)."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import AdaptiveRule, Phase, WorkoutDefinition
from ..models.enums import PhaseType


def load_definition(data: dict | str | Path) -> WorkoutDefinition:
    """Load a `WorkoutDefinition` from a dict, JSON string, or JSON file path (PRD §8)."""
    if isinstance(data, Path):
        data = json.loads(data.read_text(encoding="utf-8"))
    elif isinstance(data, str):
        # Treat as a path if it points to an existing file, else parse as JSON text.
        p = Path(data)
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else json.loads(data)

    phases = []
    for raw in data["phases"]:
        hr = raw.get("hr_target")
        phases.append(
            Phase(
                type=PhaseType(raw["type"]),
                duration_min=raw.get("duration_min"),
                distance_m=raw.get("distance_m"),
                speed_mph=raw.get("speed_mph"),
                incline_pct=raw.get("incline_pct"),
                hr_target=tuple(hr) if hr else None,
                rpe_target=raw.get("rpe_target"),
                tolerance_bpm=raw.get("tolerance_bpm", 8),
                adaptive_rules=[AdaptiveRule(**r) for r in raw.get("adaptive_rules", [])],
            )
        )
    return WorkoutDefinition(name=data.get("name", "Untitled"), phases=phases)


def standard_treadmill_session() -> WorkoutDefinition:
    """The PRD §15 controlled treadmill session with default adaptive rules."""
    return WorkoutDefinition(
        name="Standard Controlled Treadmill",
        phases=[
            Phase(type=PhaseType.WARMUP, duration_min=10, speed_mph=4.0, incline_pct=1),
            Phase(
                type=PhaseType.AEROBIC,
                duration_min=25,
                speed_mph=4.7,
                incline_pct=1,
                hr_target=(135, 150),
                adaptive_rules=[
                    AdaptiveRule(when="hr_above_target", action="reduce", detail="Ease back slightly"),
                    AdaptiveRule(when="hr_below_target", action="extend", detail="Room to add a little"),
                ],
            ),
            Phase(type=PhaseType.PROGRESSION, duration_min=5, speed_mph=5.0, incline_pct=1),
            Phase(type=PhaseType.COOLDOWN, duration_min=5, speed_mph=3.5, incline_pct=0),
        ],
    )
