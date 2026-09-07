"""Terrain-aware analysis: grade, elevation, equivalent-flat pace (PRD §9.4).

Direct pace comparison across materially different terrain is avoided; instead we expose
an equivalent-flat pace with an explicit confidence that reflects GPS/altitude quality
(PRD §9.4, §14).
"""

from __future__ import annotations

from ..models import Workout
from ..models.enums import TerrainType

# Minetti-inspired linear grade adjustment: cost rises ~+0.03 per +1% uphill grade.
GRADE_COST_UP = 0.033
GRADE_COST_DOWN = 0.018
MAX_PLAUSIBLE_GRADE = 0.30  # clamp to reject GPS/altitude noise


def elevation_profile(workout: Workout) -> dict:
    """Cumulative elevation gain/loss and average absolute grade (§9.1, §9.4)."""
    pts = workout.trackpoints
    gain = loss = 0.0
    grades: list[float] = []
    have_alt = False
    for i in range(1, len(pts)):
        a0 = pts[i - 1].altitude_m
        a1 = pts[i].altitude_m
        d0 = pts[i - 1].distance_m or 0.0
        d1 = pts[i].distance_m or 0.0
        if a0 is None or a1 is None:
            continue
        have_alt = True
        dz = a1 - a0
        dx = d1 - d0
        if dz > 0:
            gain += dz
        else:
            loss += -dz
        if dx > 1.0:
            grade = max(-MAX_PLAUSIBLE_GRADE, min(MAX_PLAUSIBLE_GRADE, dz / dx))
            grades.append(grade)
    return {
        "has_elevation": have_alt,
        "elevation_gain_m": round(gain, 1) if have_alt else None,
        "elevation_loss_m": round(loss, 1) if have_alt else None,
        "avg_abs_grade_pct": round(100 * sum(abs(g) for g in grades) / len(grades), 2)
        if grades
        else None,
    }


def infer_terrain(workout: Workout) -> TerrainType:
    """Classify terrain from GPS presence and elevation gain (§9.4, §14)."""
    pts = workout.trackpoints
    has_gps = any(p.latitude is not None for p in pts)
    if not has_gps:
        return TerrainType.TREADMILL
    prof = elevation_profile(workout)
    gain = prof.get("elevation_gain_m") or 0.0
    if gain >= 40:
        return TerrainType.HILLY_OUTDOOR
    return TerrainType.FLAT_OUTDOOR


def equivalent_flat_pace(workout: Workout) -> dict:
    """Grade-adjusted equivalent-flat pace with a confidence estimate (§9.4).

    Returns unavailable (with a reason) for treadmill or GPS-poor sessions rather than
    producing a misleading comparison.
    """
    pts = workout.trackpoints
    terrain = infer_terrain(workout)
    if terrain == TerrainType.TREADMILL:
        return {"available": False, "reason": "treadmill_no_gps", "terrain": terrain.value}

    adj_time = 0.0
    flat_distance = 0.0
    used = 0
    for i in range(1, len(pts)):
        prev, cur = pts[i - 1], pts[i]
        dx = (cur.distance_m or 0.0) - (prev.distance_m or 0.0)
        dt = (cur.timestamp - prev.timestamp).total_seconds()
        if dx <= 0 or dt <= 0:
            continue
        a0, a1 = prev.altitude_m, cur.altitude_m
        grade = 0.0
        if a0 is not None and a1 is not None:
            grade = max(-MAX_PLAUSIBLE_GRADE, min(MAX_PLAUSIBLE_GRADE, (a1 - a0) / dx))
        cost = GRADE_COST_UP if grade >= 0 else GRADE_COST_DOWN
        factor = 1.0 + cost * (grade * 100.0)
        factor = max(0.5, factor)
        # Time the athlete "would" spend on flat ground covering the same distance.
        adj_time += dt / factor
        flat_distance += dx
        used += 1

    if flat_distance <= 0:
        return {"available": False, "reason": "insufficient_distance", "terrain": terrain.value}

    eq_pace = adj_time / (flat_distance / 1000.0)
    coverage = used / max(len(pts) - 1, 1)
    confidence = round(min(1.0, coverage) * (0.9 if terrain == TerrainType.HILLY_OUTDOOR else 1.0), 2)
    return {
        "available": True,
        "terrain": terrain.value,
        "equivalent_flat_pace_s_per_km": round(eq_pace, 1),
        "confidence": confidence,
        "model": {"grade_cost_up": GRADE_COST_UP, "grade_cost_down": GRADE_COST_DOWN},
    }


def treadmill_effort(workout: Workout) -> dict:
    """Grade-adjusted effort from the athlete's reported treadmill plan (PRD §9.4, §15).

    A treadmill has no GPS, so incline is only known from what the athlete typed. This turns
    that description into numbers: each phase's speed and incline give a grade-adjusted
    equivalent-flat pace, so running at 2% is scored as harder than the same speed at 1%.
    """
    from ..ingestion.treadmill_log import MPH_TO_MPS, parse_treadmill_log

    if infer_terrain(workout) != TerrainType.TREADMILL:
        return {"available": False, "reason": "not_treadmill"}

    phases: list[dict] = []
    if workout.notes:
        try:
            for p in parse_treadmill_log(workout.notes).phases:
                phases.append({"type": p.type.value, "duration_min": p.duration_min,
                               "speed_mph": p.speed_mph, "incline_pct": p.incline_pct})
        except ValueError:
            phases = []
    if not phases and workout.treadmill_speed_mph:
        phases = [{"type": "aerobic", "duration_min": (workout.duration_s or 0) / 60.0,
                   "speed_mph": workout.treadmill_speed_mph,
                   "incline_pct": workout.treadmill_incline_pct}]
    if not phases:
        return {"available": False, "reason": "no_treadmill_plan"}

    total_time_s = 0.0
    adj_time_s = 0.0
    distance_km = 0.0
    incline_time = 0.0
    incline_weight = 0.0
    for ph in phases:
        speed_mph = ph["speed_mph"]
        dur_min = ph["duration_min"] or 0.0
        if not speed_mph or dur_min <= 0:
            continue
        grade_pct = ph["incline_pct"] or 0.0
        # Same Minetti-inspired cost the outdoor equivalent-flat pace uses.
        factor = max(0.5, 1.0 + GRADE_COST_UP * grade_pct)
        t = dur_min * 60.0
        total_time_s += t
        adj_time_s += t / factor
        distance_km += (speed_mph * MPH_TO_MPS) * t / 1000.0
        incline_time += grade_pct * dur_min
        incline_weight += dur_min

    if distance_km <= 0:
        return {"available": False, "reason": "no_speed_in_plan"}

    raw_pace = total_time_s / distance_km
    eq_pace = adj_time_s / distance_km
    return {
        "available": True,
        "terrain": TerrainType.TREADMILL.value,
        "source": "athlete_reported",
        "phases": phases,
        "avg_incline_pct": round(incline_time / incline_weight, 2) if incline_weight else 0.0,
        "distance_km": round(distance_km, 2),
        "avg_pace_s_per_km": round(raw_pace, 1),
        "equivalent_flat_pace_s_per_km": round(eq_pace, 1),
        # How much the reported incline stiffens the effort vs the same speed on the flat.
        "incline_effort_pct": round((raw_pace - eq_pace) / raw_pace * 100.0, 1),
        "model": {"grade_cost_up": GRADE_COST_UP},
    }

