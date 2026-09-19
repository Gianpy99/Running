"""Main-set isolation: the real training, separated from warmup and cooldown (§9.2, §15).

Most sessions — treadmill ones especially — start with an easy warmup and finish with an
easy cooldown. Averaging those into the session figures makes the athlete look slower than
they actually ran the work. This module finds the elapsed-time window of the "main set" so
`metrics.basic_metrics` can be re-run over just that portion.

Two strategies, in order of trust:

* ``declared`` — the athlete literally wrote "10 min warmup ..." / "5 min cooldown" in the
  treadmill description (PRD §15). Those phase durations are exact, so they are used
  verbatim; the cooldown is anchored to the end of the recording so an edited device
  session still lines up with its measured stream.
* ``detected`` — no declared plan, so leading/trailing samples that are materially slower
  than the session's own reference speed are trimmed. This is relative to the session, so
  it works regardless of how fast the athlete is.

Only *leading* and *trailing* easy running is removed: a recovery jog between two hard
efforts is part of the main set, not warmup.
"""

from __future__ import annotations

from ..models import Workout
from ..models.enums import PhaseType

# --- `detected` strategy thresholds ---
REFERENCE_PERCENTILE = 0.75  # the session's "working" speed, robust to a slow tail
EASY_SPEED_FRACTION = 0.90  # slower than this share of it at either end = warmup/cooldown
MOVING_SPEED_MPS = 0.5  # below this the athlete is stopped, not running

MIN_TRIM_S = 60.0  # trimming less than a minute is noise, not a warmup
MIN_MAIN_SET_S = 120.0  # below this there is no meaningful main set left to report


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _declared_bounds(workout: Workout) -> tuple[float, float] | None:
    """Warmup / cooldown seconds taken straight from the athlete's own description (§15)."""
    # Imported lazily: ingestion depends on analytics for nothing, but keeping the import
    # local mirrors `terrain.treadmill_effort` and avoids an import cycle at module load.
    from ..ingestion.treadmill_log import parse_treadmill_log

    if not workout.notes:
        return None
    try:
        phases = parse_treadmill_log(workout.notes).phases
    except ValueError:
        return None
    if not phases:
        return None

    warmup_s = 0.0
    for phase in phases:
        if phase.type != PhaseType.WARMUP:
            break
        warmup_s += (phase.duration_min or 0.0) * 60.0

    cooldown_s = 0.0
    for phase in reversed(phases):
        if phase.type != PhaseType.COOLDOWN:
            break
        cooldown_s += (phase.duration_min or 0.0) * 60.0

    if warmup_s <= 0 and cooldown_s <= 0:
        return None
    return warmup_s, cooldown_s


def _detected_bounds(workout: Workout) -> tuple[float, float] | None:
    """Trim leading/trailing running that is slower than the session's own working speed."""
    pts = [p for p in workout.trackpoints if p.speed_mps is not None]
    if len(pts) < 3:
        return None
    reference = _percentile([p.speed_mps for p in pts if p.speed_mps >= MOVING_SPEED_MPS], REFERENCE_PERCENTILE)
    if not reference:
        return None

    threshold = reference * EASY_SPEED_FRACTION
    working = [i for i, p in enumerate(pts) if (p.speed_mps or 0.0) >= threshold]
    if not working:
        return None

    total_s = workout.duration_s or pts[-1].elapsed_s
    warmup_s = pts[working[0]].elapsed_s
    # The last working sample still covers the interval up to the following sample.
    last = working[-1]
    end_s = pts[last + 1].elapsed_s if last + 1 < len(pts) else pts[last].elapsed_s
    return warmup_s, max(total_s - end_s, 0.0)


def main_set_window(workout: Workout) -> dict:
    """Locate the main set, returning the window plus how it was determined.

    Always returns a dict; ``available`` is False (with a ``reason``) when the session has
    no separable warmup/cooldown, so callers can show whole-session figures unchanged.
    """
    total_s = workout.duration_s or (workout.trackpoints[-1].elapsed_s if workout.trackpoints else 0.0)
    if total_s <= 0:
        return {"available": False, "reason": "no_duration"}

    method = "declared"
    bounds = _declared_bounds(workout)
    if bounds is None:
        method = "detected"
        bounds = _detected_bounds(workout)
    if bounds is None:
        return {"available": False, "reason": "no_speed_signal"}

    warmup_s, cooldown_s = bounds
    start_s = min(warmup_s, total_s)
    end_s = max(total_s - cooldown_s, start_s)
    trimmed_s = warmup_s + cooldown_s

    if trimmed_s < MIN_TRIM_S:
        return {"available": False, "reason": "no_warmup_or_cooldown", "method": method}
    if end_s - start_s < MIN_MAIN_SET_S:
        return {"available": False, "reason": "main_set_too_short", "method": method}

    return {
        "available": True,
        "method": method,
        "start_s": round(start_s, 1),
        "end_s": round(end_s, 1),
        "warmup_s": round(warmup_s, 1),
        "cooldown_s": round(cooldown_s, 1),
        "trimmed_s": round(trimmed_s, 1),
        "trimmed_pct": round(trimmed_s / total_s * 100.0, 1),
        "thresholds": {
            "reference_percentile": REFERENCE_PERCENTILE,
            "easy_speed_fraction": EASY_SPEED_FRACTION,
            "min_trim_s": MIN_TRIM_S,
            "min_main_set_s": MIN_MAIN_SET_S,
        },
    }
