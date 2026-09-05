"""Aerobic efficiency and HR drift (PRD §9.5, §9.6).

Both metrics operate only over sufficiently steady segments; otherwise they return
unavailable with a reason, never a misleading number (PRD §9.6).
"""

from __future__ import annotations

from ..models import Workout

STEADY_MIN_SECONDS = 600  # need >=10 min of steady data to trust these metrics
STEADY_SPEED_CV_MAX = 0.15  # coefficient of variation of speed for "steady"
SUSPECT_HR_MAX_FRACTION = 0.25  # abort if too much HR is flagged suspect


def _steady_points(workout: Workout):
    """Trackpoints with reliable HR and non-trivial speed."""
    return [
        p
        for p in workout.trackpoints
        if p.hr_bpm is not None and not p.is_hr_suspect and (p.speed_mps or 0) > 1.0
    ]


def _stats(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return mean, var**0.5


def aerobic_efficiency(workout: Workout) -> dict:
    """Efficiency = mean speed / mean HR over steady segments (m/s per bpm) (§9.5).

    Higher is better (more speed per heartbeat). Only comparable across similar terrain.
    """
    pts = _steady_points(workout)
    duration = pts[-1].elapsed_s - pts[0].elapsed_s if len(pts) >= 2 else 0
    if duration < STEADY_MIN_SECONDS:
        return {"available": False, "reason": "insufficient_steady_data"}
    speeds = [p.speed_mps for p in pts]
    mean_speed, sd_speed = _stats(speeds)
    cv = sd_speed / mean_speed if mean_speed else 1.0
    if cv > STEADY_SPEED_CV_MAX:
        return {"available": False, "reason": "not_steady_enough", "speed_cv": round(cv, 3)}
    mean_hr = sum(p.hr_bpm for p in pts) / len(pts)
    if mean_hr <= 0:
        return {"available": False, "reason": "no_hr"}
    return {
        "available": True,
        "efficiency_mps_per_bpm": round(mean_speed / mean_hr, 5),
        "mean_speed_mps": round(mean_speed, 3),
        "mean_hr": round(mean_hr, 1),
        "steady_seconds": round(duration, 1),
    }


def hr_drift(workout: Workout) -> dict:
    """Decoupling of pace:HR between first and second half of a steady run (§9.6).

    Reported as percent change in HR/speed ratio. Unavailable unless the session is
    steady with adequate data.
    """
    pts = _steady_points(workout)
    total = len(workout.trackpoints)
    suspect = sum(1 for p in workout.trackpoints if p.is_hr_suspect)
    if total and suspect / total > SUSPECT_HR_MAX_FRACTION:
        return {"available": False, "reason": "too_much_suspect_hr"}
    duration = pts[-1].elapsed_s - pts[0].elapsed_s if len(pts) >= 2 else 0
    if duration < STEADY_MIN_SECONDS:
        return {"available": False, "reason": "insufficient_steady_data"}

    mid = len(pts) // 2
    first, second = pts[:mid], pts[mid:]

    def ratio(seg) -> float | None:
        sp = [p.speed_mps for p in seg]
        hr = [p.hr_bpm for p in seg]
        mean_sp = sum(sp) / len(sp)
        mean_hr = sum(hr) / len(hr)
        if mean_sp <= 0:
            return None
        return mean_hr / mean_sp  # bpm per m/s; rises as athlete fatigues

    r1, r2 = ratio(first), ratio(second)
    if not r1 or not r2:
        return {"available": False, "reason": "no_hr"}
    drift_pct = (r2 - r1) / r1 * 100.0
    return {
        "available": True,
        "drift_pct": round(drift_pct, 2),
        "first_half_bpm_per_mps": round(r1, 2),
        "second_half_bpm_per_mps": round(r2, 2),
        "interpretation": "aerobically_decoupled" if drift_pct > 5 else "aerobically_stable",
    }
