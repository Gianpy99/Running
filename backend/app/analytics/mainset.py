"""Main-set isolation: the real training, separated from warmup and cooldown (§9.2, §15).

Treadmill sessions habitually open with an easy warmup and close with an easy cooldown.
Averaged into the session figures they make a good main set look slower than it was run,
so this module locates the main set's elapsed-time window and re-runs the metrics over it.

Scope is deliberately limited to treadmill sessions. Outdoor runs keep their calculated
session figures: trimming their ends by pace produced windows driven by GPS noise — a
single fast sample at the start, a slow one at the end — which moved the reported pace by
a second or two for no real reason.

How the easy ends are established, in order of trust:

* ``declared`` — the athlete described the phases ("10 min warmup ... 5 min cooldown").
  Those are exact and are used verbatim. A description that declares no warmup or cooldown
  means there was none, and overrides the habitual default below.
* ``athlete_default`` — no description, so the athlete's habitual treadmill structure
  (`Athlete.treadmill_warmup` / `treadmill_cooldown`) is applied.

Pace over that window needs to know how the distance was spread across the session.
Treadmill exports commonly carry heart rate only: one total `DistanceMeters` on the lap,
with every trackpoint reporting zero distance and no speed. The session average survives
that (total distance / total time) but the split does not. So the easy ends are priced
from their phase speeds and subtracted from the *measured* session total, which keeps the
recording authoritative and only models the part that was never recorded. Where not even
that is possible, pace is reported unavailable with a reason rather than guessed;
main-set heart rate, which is genuinely measured, is returned either way.
"""

from __future__ import annotations

from ..models import Athlete, Workout
from ..models.enums import PhaseType, TerrainType
from .metrics import basic_metrics
from .terrain import infer_terrain

MIN_MAIN_SET_S = 120.0  # below this there is nothing meaningful left to call a main set
_PROFILE_STEP_S = 10.0  # resolution used to integrate a phase plan


def _declared_phases(workout: Workout) -> list | None:
    """The athlete's own phase description, parsed; None when absent or unparseable."""
    # Imported lazily to mirror `terrain.treadmill_effort` and avoid an import cycle.
    from ..ingestion.treadmill_log import parse_treadmill_log

    if not workout.notes:
        return None
    try:
        phases = parse_treadmill_log(workout.notes).phases
    except ValueError:
        return None
    return phases or None


def _duration_s(phases: list) -> float:
    return sum((p.duration_min or 0.0) * 60.0 for p in phases)


def _phase_distance_m(phases: list, start_s: float, end_s: float) -> float:
    """Distance the phase plan covers between `start_s` and `end_s` on its own timeline.

    Integrated with the same per-phase speed rule the treadmill synthesiser uses, so a
    cooldown written without a speed ramps down exactly as it does elsewhere. Phases with
    no stated speed and no ramp to inherit contribute nothing.
    """
    from ..ingestion.treadmill_log import _phase_speed_mps

    distance_m = 0.0
    cursor = 0.0
    prev_speed_mph: float | None = None
    for phase in phases:
        phase_s = (phase.duration_min or 0.0) * 60.0
        t = 0.0
        while t < phase_s:
            step = min(_PROFILE_STEP_S, phase_s - t)
            sample_start, sample_end = cursor + t, cursor + t + step
            overlap = min(sample_end, end_s) - max(sample_start, start_s)
            if overlap > 0:
                speed_mps = _phase_speed_mps(phase, t, prev_speed_mph)
                if speed_mps:
                    distance_m += speed_mps * overlap
            t += step
        if phase.speed_mph:
            prev_speed_mph = phase.speed_mph
        cursor += phase_s
    return distance_m


def _easy_ends(workout: Workout, athlete: Athlete) -> dict:
    """Duration and distance of the warmup and cooldown, plus how they were established."""
    phases = _declared_phases(workout)
    if phases is not None:
        warmup, cooldown = [], []
        for phase in phases:
            if phase.type != PhaseType.WARMUP:
                break
            warmup.append(phase)
        for phase in reversed(phases):
            if phase.type != PhaseType.COOLDOWN:
                break
            cooldown.insert(0, phase)
        # Priced across the whole plan so a speed-less cooldown can still ramp down from
        # the speed of the phase before it.
        plan_s = _duration_s(phases)
        warmup_s, cooldown_s = _duration_s(warmup), _duration_s(cooldown)
        return {
            "method": "declared",
            "warmup_s": warmup_s,
            "cooldown_s": cooldown_s,
            "warmup_m": _phase_distance_m(phases, 0.0, warmup_s),
            "cooldown_m": _phase_distance_m(phases, max(plan_s - cooldown_s, 0.0), plan_s),
        }

    warmup, cooldown = athlete.treadmill_warmup, athlete.treadmill_cooldown
    warmup_s, cooldown_s = _duration_s(warmup), _duration_s(cooldown)
    return {
        "method": "athlete_default",
        "warmup_s": warmup_s,
        "cooldown_s": cooldown_s,
        "warmup_m": _phase_distance_m(warmup, 0.0, warmup_s),
        "cooldown_m": _phase_distance_m(cooldown, 0.0, cooldown_s),
    }


def main_set_window(workout: Workout, athlete: Athlete | None = None) -> dict:
    """Locate the main set, returning the window and how it was determined.

    ``available`` is False (with a ``reason``) when the session has no separable
    warmup/cooldown, so callers fall back to the calculated session figures.
    """
    athlete = athlete or Athlete()
    if infer_terrain(workout) != TerrainType.TREADMILL:
        return {"available": False, "reason": "not_treadmill"}

    pts = workout.trackpoints
    total_s = workout.duration_s or (pts[-1].elapsed_s if pts else 0.0)
    if total_s <= 0:
        return {"available": False, "reason": "no_duration"}

    ends = _easy_ends(workout, athlete)
    warmup_s, cooldown_s = ends["warmup_s"], ends["cooldown_s"]
    if warmup_s <= 0 and cooldown_s <= 0:
        return {"available": False, "reason": "no_warmup_or_cooldown", "method": ends["method"]}

    start_s = min(warmup_s, total_s)
    end_s = max(total_s - cooldown_s, start_s)
    if end_s - start_s < MIN_MAIN_SET_S:
        return {"available": False, "reason": "main_set_too_short", "method": ends["method"]}

    trimmed_s = warmup_s + cooldown_s
    return {
        "available": True,
        "method": ends["method"],
        "start_s": round(start_s, 1),
        "end_s": round(end_s, 1),
        "warmup_s": round(warmup_s, 1),
        "cooldown_s": round(cooldown_s, 1),
        "warmup_m": round(ends["warmup_m"], 1),
        "cooldown_m": round(ends["cooldown_m"], 1),
        "trimmed_s": round(trimmed_s, 1),
        "trimmed_pct": round(trimmed_s / total_s * 100.0, 1),
    }


def main_set_metrics(workout: Workout, athlete: Athlete | None = None) -> dict:
    """`basic_metrics` over the main set, plus the window and how it was found."""
    window = main_set_window(workout, athlete)
    if not window.get("available"):
        return window

    metrics = basic_metrics(workout, window=(window["start_s"], window["end_s"]))
    duration_s = metrics["duration_s"]

    if metrics["avg_pace_s_per_km"] is not None:
        metrics["pace_source"] = "recorded"
        return {**window, **metrics}

    # The trackpoints carry no distance inside the window, so price the easy ends from
    # their phase speeds and take them off the measured session total.
    easy_m = window["warmup_m"] + window["cooldown_m"]
    distance_m = workout.distance_m - easy_m if workout.distance_m > 0 and easy_m > 0 else 0.0
    if distance_m > 0 and duration_s > 0:
        metrics["distance_m"] = round(distance_m, 1)
        metrics["avg_speed_mps"] = round(distance_m / duration_s, 3)
        metrics["avg_pace_s_per_km"] = round(duration_s / (distance_m / 1000.0), 1)
        metrics["moving_s"] = duration_s
        metrics["pace_source"] = "session_total_minus_easy_ends"
    else:
        # Heart rate is genuinely measured, so it is still reported; only pace is unknown.
        metrics["distance_m"] = None
        metrics["avg_speed_mps"] = None
        metrics["pace_reason"] = "no_distance_recorded"
    return {**window, **metrics}
