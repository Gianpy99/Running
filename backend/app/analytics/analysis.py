"""Workout analysis aggregator (PRD §9, §13).

Runs the deterministic analytics pipeline over one workout and returns a single,
reproducible analysis document with provenance (thresholds/models) attached.
"""

from __future__ import annotations

from ..models import Athlete, Workout
from .efficiency import aerobic_efficiency, hr_drift
from .load import training_load
from .metrics import basic_metrics, hr_zone_distribution, splits
from .quality import annotate_hr_quality, quality_summary
from .segmentation import main_set_window, segment_workout
from .terrain import elevation_profile, equivalent_flat_pace, infer_terrain, treadmill_effort


def _main_set_metrics(workout: Workout, whole: dict) -> dict:
    """Stats for the "real" training, with any leading warmup / trailing cooldown trimmed.

    Treadmill sessions in particular tend to start with an easy warmup and end with an
    easy cooldown, which drags down whole-session averages like pace (PRD §15). This
    re-runs `basic_metrics` over just the trimmed window so athletes can see both figures.
    """
    window = main_set_window(workout)
    if window is None:
        return {"available": False, "reason": "no_main_set_detected"}

    trimmed = round(whole["duration_s"] - (window[1] - window[0]), 1)
    if trimmed <= 0:
        # Nothing meaningful was trimmed (e.g. no warmup/cooldown segment detected).
        return {"available": False, "reason": "no_warmup_or_cooldown_detected"}

    main = basic_metrics(workout, window=window)
    return {
        "available": True,
        "window_s": [round(window[0], 1), round(window[1], 1)],
        "trimmed_s": trimmed,
        "trimmed_pct": round(trimmed / whole["duration_s"] * 100.0, 1) if whole["duration_s"] else None,
        **main,
    }


def analyse_workout(workout: Workout, athlete: Athlete, rpe: int | None = None) -> dict:
    """Full analysis. Mutates the workout only to attach HR quality flags."""
    hr_quality = annotate_hr_quality(workout)

    metrics = basic_metrics(workout)
    workout.avg_hr = metrics["avg_hr"]
    workout.avg_pace_s_per_km = metrics["avg_pace_s_per_km"]

    elevation = elevation_profile(workout)
    workout.elevation_gain_m = elevation.get("elevation_gain_m")
    workout.elevation_loss_m = elevation.get("elevation_loss_m")

    return {
        "workout_id": workout.id,
        "source_file": workout.source_file,
        "start_time": workout.start_time.isoformat(),
        "session_type": workout.session_type.value,
        "terrain": infer_terrain(workout).value,
        "completion": workout.completion.value,
        "metrics": metrics,
        "metrics_main_set": _main_set_metrics(workout, metrics),
        "hr_zones": hr_zone_distribution(workout, athlete),
        "splits": splits(workout),
        "segmentation": segment_workout(workout),
        "elevation": elevation,
        "equivalent_flat_pace": equivalent_flat_pace(workout),
        "treadmill_effort": treadmill_effort(workout),
        "aerobic_efficiency": aerobic_efficiency(workout),
        "hr_drift": hr_drift(workout),
        "training_load": training_load(workout, athlete, rpe=rpe),
        "hr_quality": {
            "flagged_samples": hr_quality.flagged_samples,
            "total_samples": hr_quality.total_samples,
            "suspect_fraction": round(hr_quality.suspect_fraction, 3),
            "thresholds": hr_quality.thresholds,
        },
        "data_quality": quality_summary(workout),
    }
