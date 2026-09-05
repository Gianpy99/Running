"""Readiness v0 — transparent, deterministic traffic-light rules (PRD §10, §26).

Every contribution is explained and traceable to an input (PRD §4, §10). The engine
never diagnoses injury or illness (PRD §10, §18); it only recommends
proceed / reduce / rest and can advise stopping on concerning symptoms.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Athlete, RecoveryContext
from ..models.enums import ReadinessLevel


@dataclass
class ReadinessResult:
    level: ReadinessLevel
    score: int  # 0..100, higher = more ready
    reasons: list[str] = field(default_factory=list)
    stop_workout: bool = False  # safety override (PRD §10, §18)
    recommendation: str = ""
    inputs: dict = field(default_factory=dict)


def compute_readiness(
    context: RecoveryContext | None,
    athlete: Athlete,
    recent_load_7d: float = 0.0,
    recent_load_28d: float = 0.0,
    last_session_hard: bool = False,
) -> ReadinessResult:
    """Compute a readiness score from recovery context and recent training load.

    Starts at 100 and applies transparent penalties. Concerning pain or illness forces
    a red / stop result regardless of score.
    """
    score = 100
    reasons: list[str] = []
    stop = False

    # --- Safety overrides first (PRD §18) ---
    if context and context.concerning_pain:
        return ReadinessResult(
            level=ReadinessLevel.RED,
            score=0,
            reasons=["Concerning/localized pain reported — do not escalate intensity."],
            stop_workout=True,
            recommendation="Rest. Concerning pain should stop the workout; seek advice if persistent.",
            inputs={"concerning_pain": True},
        )

    if context and context.illness:
        score -= 40
        reasons.append("Illness reported (-40).")

    # --- Sleep ---
    if context and context.sleep_hours is not None:
        if context.sleep_hours < 5:
            score -= 25
            reasons.append(f"Very short sleep {context.sleep_hours:g}h (-25).")
        elif context.sleep_hours < 6.5:
            score -= 12
            reasons.append(f"Below-target sleep {context.sleep_hours:g}h (-12).")
    if context and context.sleep_score is not None and context.sleep_score < 60:
        score -= 8
        reasons.append(f"Low sleep score {context.sleep_score} (-8).")

    # --- Resting HR elevation vs athlete baseline ---
    if context and context.resting_hr is not None and athlete.resting_hr:
        delta = context.resting_hr - athlete.resting_hr
        if delta >= 8:
            score -= 15
            reasons.append(f"Resting HR +{delta} over baseline (-15).")
        elif delta >= 4:
            score -= 7
            reasons.append(f"Resting HR +{delta} over baseline (-7).")

    # --- Leg fatigue (1 fresh .. 5 very heavy) ---
    if context and context.leg_fatigue is not None and context.leg_fatigue >= 4:
        score -= 15
        reasons.append(f"Heavy legs (fatigue {context.leg_fatigue}/5) (-15).")
    elif context and context.leg_fatigue == 3:
        score -= 6
        reasons.append("Moderate leg fatigue (-6).")

    # --- Subjective energy (1 low .. 5 high) ---
    if context and context.subjective_energy is not None and context.subjective_energy <= 2:
        score -= 10
        reasons.append(f"Low subjective energy ({context.subjective_energy}/5) (-10).")

    # --- GI discomfort ---
    if context and context.gi_discomfort:
        score -= 8
        reasons.append("GI discomfort reported (-8).")

    # --- Training-load context: acute:chronic ratio (spike = fatigue risk) ---
    if recent_load_28d > 0:
        acwr = recent_load_7d / (recent_load_28d / 4.0)
        if acwr > 1.5:
            score -= 15
            reasons.append(f"Acute:chronic load ratio {acwr:.2f} high (-15).")
        elif acwr > 1.3:
            score -= 8
            reasons.append(f"Acute:chronic load ratio {acwr:.2f} elevated (-8).")

    if last_session_hard:
        score -= 8
        reasons.append("Previous session was hard (-8).")

    score = max(0, min(100, score))

    if score >= 75:
        level = ReadinessLevel.GREEN
        rec = "Proceed as planned."
    elif score >= 50:
        level = ReadinessLevel.AMBER
        rec = "Reduce intensity and/or duration; keep it comfortable."
    else:
        level = ReadinessLevel.RED
        rec = "Recovery or rest today. Do not stack intensity to compensate."

    if not reasons:
        reasons.append("No limiting context reported.")

    return ReadinessResult(
        level=level,
        score=score,
        reasons=reasons,
        stop_workout=stop,
        recommendation=rec,
        inputs={
            "recent_load_7d": recent_load_7d,
            "recent_load_28d": recent_load_28d,
            "last_session_hard": last_session_hard,
        },
    )
