"""Presentation labels distinguish session structure from reported exertion."""

from __future__ import annotations

from typing import TypedDict


class EffortLabel(TypedDict):
    rpe: int | None
    label: str
    level: int
    source: str


class SessionLabel(TypedDict):
    code: str
    label: str
    detail: str
    source: str
    detected_type: str
    effort: EffortLabel


SESSION_NAMES = {
    "easy": "Easy run", "recovery": "Recovery", "progression": "Progression",
    "fartlek": "Fartlek", "interval": "Intervals", "benchmark": "Benchmark",
    "family_fun": "Family run", "incomplete": "Incomplete",
    "unclassified": "Unclassified", "steady": "Steady run",
}


def effort_label(rpe: int | None) -> EffortLabel:
    if rpe is None:
        return {"rpe": None, "label": "Effort not logged", "level": 0, "source": "unknown"}
    if not 1 <= rpe <= 10:
        raise ValueError("Reported effort must be between 1 and 10.")
    names = ["Very easy", "Comfortable", "Moderate", "Hard", "Very hard"]
    level = (rpe + 1) // 2
    return {"rpe": rpe, "label": names[level - 1], "level": level, "source": "athlete_reported"}


def describe_session(analysis: dict, feedback: dict | None = None) -> SessionLabel:
    detected = analysis.get("session_type") or "unclassified"
    code = detected
    label = SESSION_NAMES[code]
    source = "automatic"
    detail = "Automatic type estimate; not a measured effort rating."
    plan = analysis.get("treadmill_effort", {})
    phases = plan.get("phases", []) if plan.get("available") else []
    if phases and detected in ("easy", "recovery", "unclassified"):
        work = [phase for phase in phases if phase["type"] == "interval"]
        if work:
            code = "interval"
            label = "Intervals" if len(work) > 1 else "Quality block"
            blocks = "block" if len(work) == 1 else "blocks"
            detail = f"{len(work)} reported work {blocks}; intensity is not inferred from speed."
        elif any(phase["type"] == "progression" for phase in phases):
            code, label = "progression", "Progression"
            detail = "Progression explicitly reported in the treadmill phases."
        elif any(phase["type"] == "aerobic" for phase in phases):
            code, label = "steady", "Steady run"
            detail = "Reported aerobic treadmill structure; not proof of easy effort."
        if code != detected:
            source = "athlete_reported_structure"
    return {
        "code": code, "label": label, "detail": detail, "source": source,
        "detected_type": detected,
        "effort": effort_label((feedback or {}).get("perceived_exertion")),
    }
