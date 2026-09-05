"""Deterministic session classification (PRD §5.1, §14).

Classifies easy / recovery / progression / fartlek / interval / benchmark / family_fun /
incomplete from measured trackpoints and segment structure. Transparent, rule-based —
no AI (PRD §4, §12).
"""

from __future__ import annotations

from ..analytics.segmentation import segment_workout
from ..models import Workout
from ..models.enums import CompletionStatus, SessionType, SegmentType, TerrainType

# Heuristic thresholds (documented for reproducibility).
FAMILY_RUN_MAX_DISTANCE_M = 2500  # short son-run ~2 km (PRD §14)
INTERRUPTED_MIN_EXPECTED_S = 900  # sessions much shorter than planned look interrupted
BENCHMARK_MIN_INTENSITY = 0.90  # sustained high effort → benchmark/race


def classify_session(workout: Workout, expected_duration_s: float | None = None) -> SessionType:
    """Return the most likely session type using measured structure and context."""
    if workout.completion == CompletionStatus.INTERRUPTED:
        return SessionType.INCOMPLETE

    seg = segment_workout(workout)["segments"]
    fast = [s for s in seg if s["type"] in (SegmentType.FAST.value, SegmentType.MODERATE.value)]
    recovery = [s for s in seg if s["type"] == SegmentType.RECOVERY.value]
    fast_count = len(fast)

    distance = workout.distance_m
    duration = workout.duration_s

    # Family/fun: short outdoor run that is comparatively intense (PRD §14, the son-run).
    # "Intense" = a fast/moderate segment, or a high average HR for such a short outing.
    is_outdoor = workout.terrain in (TerrainType.FLAT_OUTDOOR, TerrainType.HILLY_OUTDOOR)
    if distance and distance <= FAMILY_RUN_MAX_DISTANCE_M and duration and duration < 1200:
        avg_hr = _avg_hr(workout)
        intense = fast_count >= 1 or (avg_hr is not None and avg_hr >= 155)
        if is_outdoor and intense:
            return SessionType.FAMILY_FUN

    # Interrupted: far shorter than the planned/expected session.
    if expected_duration_s and duration < 0.5 * expected_duration_s and duration < INTERRUPTED_MIN_EXPECTED_S:
        return SessionType.INCOMPLETE

    # Interval / fartlek: repeated fast blocks separated by recovery.
    if fast_count >= 3 and recovery:
        # Regular, structured repeats read as intervals; irregular as fartlek.
        return SessionType.INTERVAL if _is_regular(fast) else SessionType.FARTLEK

    # Progression: speed clearly rises across the session's running segments.
    if _is_progression(seg):
        return SessionType.PROGRESSION

    # Benchmark: mostly sustained high effort.
    hard = [s for s in seg if s["type"] == SegmentType.FAST.value]
    hard_time = sum(s["duration_s"] for s in hard)
    if duration and hard_time / duration > 0.5:
        return SessionType.BENCHMARK

    # Recovery vs easy by overall pace/HR.
    if workout.avg_pace_s_per_km and workout.avg_pace_s_per_km > 480:  # slower than 8:00/km
        return SessionType.RECOVERY
    return SessionType.EASY


def _avg_hr(workout: Workout) -> float | None:
    """Average of reliable HR readings, independent of pipeline ordering."""
    hrs = [p.hr_bpm for p in workout.trackpoints if p.hr_bpm is not None and not p.is_hr_suspect]
    return sum(hrs) / len(hrs) if hrs else None


def _is_regular(fast_segments: list[dict]) -> bool:
    durations = [s["duration_s"] for s in fast_segments]
    if len(durations) < 2:
        return True
    mean = sum(durations) / len(durations)
    if mean <= 0:
        return False
    var = sum((d - mean) ** 2 for d in durations) / len(durations)
    return (var**0.5) / mean < 0.35  # low variability → structured intervals


def _is_progression(segments: list[dict]) -> bool:
    running = [
        s for s in segments
        if s["type"] not in (SegmentType.PAUSED.value, SegmentType.WALKING.value)
        and s["avg_speed_mps"]
    ]
    if len(running) < 3:
        return False
    speeds = [s["avg_speed_mps"] for s in running]
    first_third = speeds[: len(speeds) // 3] or speeds[:1]
    last_third = speeds[-len(speeds) // 3:] or speeds[-1:]
    avg_first = sum(first_third) / len(first_third)
    avg_last = sum(last_third) / len(last_third)
    return avg_last > avg_first * 1.10  # >10% faster by the end
