"""Ingestion → analysis pipeline and data-quality reporting (PRD §5, §23, §25).

Reprocesses raw sources reproducibly (PRD §27). Files that cannot be parsed are
quarantined with a reason rather than silently dropped (PRD §25).
"""

from __future__ import annotations

from pathlib import Path

from ..analytics.analysis import analyse_workout
from ..analytics.terrain import infer_terrain
from ..ingestion import parse_tcx_file, read_scale_xls
from ..models import Athlete, Workout
from .classification import classify_session


def process_tcx_file(path: str | Path, athlete: Athlete) -> tuple[Workout, dict]:
    """Parse, classify and analyse a single TCX file into (workout, analysis)."""
    workout = parse_tcx_file(path)
    workout.terrain = infer_terrain(workout)
    # Classify before analysis so load accounting reflects the session type (§9.7).
    workout.session_type = classify_session(workout)
    analysis = analyse_workout(workout, athlete)
    # Re-run load now that avg pace/HR are populated is unnecessary; analysis already did.
    return workout, analysis


def reanalyse_stored_workouts(store, athlete: Athlete | None = None, only_missing: bool = True) -> int:
    """Re-run the analytics pipeline over workouts already in the store (PRD §27).

    The canonical trackpoints are persisted alongside each workout, so analyses can be
    regenerated without the raw files. Used to backfill fields added after a session was
    first imported (e.g. main-set metrics) without forcing a full re-import.

    With ``only_missing`` (the default) a workout is skipped when its stored analysis
    already carries the newest fields, making startup backfill effectively free.
    Returns the number of workouts re-analysed.
    """
    athlete = athlete or Athlete()
    updated = 0
    for row in store.list_workouts():
        if only_missing and "metrics_main_set" in (store.get_analysis(row["id"]) or {}):
            continue
        workout = store.get_workout(row["id"])
        if workout is None or not workout.trackpoints:
            continue
        analysis = analyse_workout(workout, athlete)
        store.upsert_workout(workout, analysis)
        updated += 1
    return updated


def process_raw_directory(
    raw_dir: str | Path, athlete: Athlete | None = None
) -> dict:
    """Process every TCX and smart-scale file under `raw_dir` (non-recursive + this dir).

    Returns a data-quality report (PRD §23) listing imported workouts, per-file quality
    summaries and quarantined files with reasons.
    """
    athlete = athlete or Athlete()
    raw = Path(raw_dir)

    workouts: list[tuple[Workout, dict]] = []
    quarantined: list[dict] = []

    # Scan the given directory only (non-recursive) so nested project folders such as
    # data/regression are never double-counted.
    tcx_files = sorted(raw.glob("*.tcx"))
    for f in tcx_files:
        try:
            workouts.append(process_tcx_file(f, athlete))
        except Exception as exc:  # quarantine, don't crash the batch (PRD §25)
            quarantined.append({"file": f.name, "reason": f"{type(exc).__name__}: {exc}"})

    # Smart-scale files.
    body_count = 0
    scale_files = sorted(raw.glob("*.xls")) + sorted(raw.glob("*.xlsx"))
    body_measurements = []
    for f in scale_files:
        try:
            ms = read_scale_xls(f)
            body_measurements.extend(ms)
            body_count += len(ms)
        except Exception as exc:
            quarantined.append({"file": f.name, "reason": f"scale_read_error: {exc}"})

    report = _build_report(workouts, body_measurements, body_count, quarantined)
    report["_workouts"] = workouts  # attached for the caller; not part of the JSON schema
    report["_body_measurements"] = body_measurements
    return report


def _build_report(workouts, body_measurements, body_count, quarantined) -> dict:
    session_breakdown: dict[str, int] = {}
    files_summary = []
    total_distance = 0.0
    total_duration = 0.0
    for w, analysis in workouts:
        session_breakdown[w.session_type.value] = session_breakdown.get(w.session_type.value, 0) + 1
        total_distance += w.distance_m
        total_duration += w.duration_s
        files_summary.append(
            {
                "workout_id": w.id,
                "source_file": w.source_file,
                "start_time": w.start_time.isoformat(),
                "session_type": w.session_type.value,
                "terrain": w.terrain.value,
                "completion": w.completion.value,
                "distance_m": round(w.distance_m, 1),
                "duration_s": round(w.duration_s, 1),
                "avg_hr": w.avg_hr,
                "hr_suspect_fraction": analysis["hr_quality"]["suspect_fraction"],
                "data_quality": analysis["data_quality"],
            }
        )

    return {
        "generated_from": "raw TCX/XLS (authoritative sources reprocessed)",  # PRD §27
        "summary": {
            "workouts_imported": len(workouts),
            "workouts_quarantined": len(quarantined),
            "body_measurements": body_count,
            "total_distance_km": round(total_distance / 1000.0, 2),
            "total_duration_min": round(total_duration / 60.0, 1),
            "session_breakdown": session_breakdown,
        },
        "workouts": files_summary,
        "quarantined": quarantined,
    }
