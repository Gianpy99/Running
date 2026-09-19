"""Deterministic narrator + AI provenance envelope (PRD §12)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

PROMPT_VERSION = "narrator-v0"


def build_feature_snapshot(analysis: dict) -> dict:
    """Minimal, machine-consumable features sent to any AI call (PRD §12)."""
    m = analysis.get("metrics", {})
    return {
        "session_type": analysis.get("session_type"),
        "terrain": analysis.get("terrain"),
        "completion": analysis.get("completion"),
        "distance_km": round((m.get("distance_m") or 0) / 1000.0, 2),
        "duration_min": round((m.get("duration_s") or 0) / 60.0, 1),
        "avg_hr": m.get("avg_hr"),
        "avg_pace_s_per_km": m.get("avg_pace_s_per_km"),
        "main_set": analysis.get("metrics_main_set", {}),
        "hr_drift": analysis.get("hr_drift", {}),
        "aerobic_efficiency": analysis.get("aerobic_efficiency", {}),
        "hr_suspect_fraction": analysis.get("hr_quality", {}).get("suspect_fraction"),
        "equivalent_flat_pace": analysis.get("equivalent_flat_pace", {}),
        "treadmill_effort": analysis.get("treadmill_effort", {}),
    }


def _envelope(kind: str, snapshot: dict, output: dict) -> dict:
    """Provenance wrapper stored for reproducibility (PRD §12)."""
    snap_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()[:16]
    return {
        "kind": kind,
        "prompt_version": PROMPT_VERSION,
        "model": "deterministic-fallback",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feature_snapshot": snapshot,
        "feature_snapshot_sha256": snap_hash,
        "output": output,
    }


def _pace_str(seconds: float | None) -> str:
    if not seconds:
        return "n/a"
    # Rounded, not truncated, to match how the dashboard formats the same number.
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}/km"


def explain_session(analysis: dict) -> dict:
    """Produce a structured session narrative from evidence (PRD §12, §26)."""
    snap = build_feature_snapshot(analysis)
    parts = [
        f"{snap['session_type']} session on {snap['terrain']} terrain: "
        f"{snap['distance_km']} km in {snap['duration_min']} min "
        f"(avg pace {_pace_str(snap['avg_pace_s_per_km'])}, avg HR "
        f"{snap['avg_hr'] if snap['avg_hr'] else 'n/a'} bpm)."
    ]
    main = snap.get("main_set", {})
    if main.get("available") and main.get("avg_pace_s_per_km"):
        # The headline pace above includes the easy ends; quote the work on its own so a
        # warmup-heavy session is not mistaken for a slow one (§15).
        estimated = main.get("pace_source") == "session_total_minus_easy_ends"
        parts.append(
            f"Excluding {round(main['warmup_s'] / 60)} min warmup and "
            f"{round(main['cooldown_s'] / 60)} min cooldown "
            f"({round(main['duration_s'] / 60)} min of work), the main set averaged "
            f"{_pace_str(main['avg_pace_s_per_km'])}"
            + (f" at {main['avg_hr']} bpm" if main.get("avg_hr") else "")
            + (" (pace estimated: this export records heart rate only)." if estimated else ".")
        )
    elif main.get("available"):
        parts.append(
            f"Excluding {round(main['warmup_s'] / 60)} min warmup and "
            f"{round(main['cooldown_s'] / 60)} min cooldown, the main set averaged "
            f"{main['avg_hr']} bpm; pace could not be separated because no distance was recorded."
            if main.get("avg_hr") else
            "Main set could not be measured separately: no distance or heart rate was recorded."
        )
    drift = snap["hr_drift"]
    if drift.get("available"):
        parts.append(
            f"HR drift {drift['drift_pct']}% — {drift['interpretation'].replace('_', ' ')}."
        )
    else:
        parts.append("HR drift not assessed (insufficiently steady data).")
    if snap["hr_suspect_fraction"] and snap["hr_suspect_fraction"] > 0.1:
        parts.append(
            f"Caution: {round(snap['hr_suspect_fraction'] * 100)}% of HR samples were "
            "flagged suspect; physiological readings are down-weighted."
        )
    eff = snap["aerobic_efficiency"]
    if eff.get("available"):
        parts.append(f"Aerobic efficiency {eff['efficiency_mps_per_bpm']} m/s per bpm.")

    tm = snap.get("treadmill_effort", {})
    if tm.get("available"):
        parts.append(
            f"Treadmill plan (reported): {tm['avg_incline_pct']}% avg incline, "
            f"grade-adjusted equivalent-flat pace {_pace_str(tm['equivalent_flat_pace_s_per_km'])} "
            f"(incline adds ~{tm['incline_effort_pct']}% effort vs the same speed on the flat)."
        )

    output = {
        "narrative": " ".join(parts),
        "flags": [] if not snap["hr_suspect_fraction"] or snap["hr_suspect_fraction"] <= 0.1
        else ["hr_quality_caution"],
    }
    return _envelope("session_explanation", snap, output)


def recommend_next_session(analysis: dict, readiness: dict) -> dict:
    """Structured next-session suggestion. Deterministic planner remains authoritative."""
    snap = build_feature_snapshot(analysis)
    level = readiness.get("level", "green")
    if level == "red":
        rec = "Rest or very easy recovery. Do not stack intensity."
    elif level == "amber":
        rec = "Keep it easy and aerobic; reduce duration if legs stay heavy."
    else:
        rec = "Proceed with the planned session; hold HR in the aerobic band."
    output = {"recommendation": rec, "readiness_level": level, "requires_validation": True}
    return _envelope("next_session_recommendation", {**snap, "readiness": readiness}, output)
