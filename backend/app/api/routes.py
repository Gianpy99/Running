"""HTTP API implementing the PRD §20 sketch.

Deterministic analytics back the endpoints; the /ai/* routes return the provenance-wrapped
narrator output (PRD §12). Real-time/safety logic is never delegated to AI.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..ai import explain_session, recommend_next_session
from ..analytics.analysis import analyse_workout
from ..analytics.terrain import infer_terrain
from ..ingestion import build_treadmill_workout, parse_tcx, parse_treadmill_log
from ..models import Athlete, RecoveryContext
from ..persistence import open_store
from ..persistence.store import _BaseStore
from ..services.body_trends import weight_trend
from ..services.classification import classify_session
from ..services.pipeline import process_raw_directory
from ..services.readiness import compute_readiness
from ..training.dsl import load_definition, standard_treadmill_session
from ..training.planner import adapt_definition, generate_next_session

ATHLETE = Athlete()

_DASHBOARD_HTML = Path(__file__).parent / "static" / "index.html"


class RecoveryIn(BaseModel):
    for_date: date
    sleep_hours: float | None = None
    sleep_score: int | None = None
    resting_hr: int | None = None
    subjective_energy: int | None = None
    leg_fatigue: int | None = None
    gi_discomfort: bool = False
    illness: bool = False
    concerning_pain: bool = False
    notes: str | None = None


class RaceIn(BaseModel):
    name: str
    race_date: str | None = None
    distance_m: float | None = None
    target_time_s: int | None = None
    verified: bool = False


class TreadmillLogIn(BaseModel):
    """A free-text treadmill session, one phase per line (PRD §15)."""

    description: str
    start_time: datetime | None = None
    avg_hr: int | None = None
    workout_id: str | None = None  # set to overwrite an existing session (retroactive edit)


def _recent_loads(store: _BaseStore) -> tuple[float, float, bool]:
    """Sum 7-day and 28-day planned training load from stored analyses."""
    now = datetime.now(timezone.utc)
    load_7 = load_28 = 0.0
    last_hard = False
    latest_time = None
    for w in store.list_workouts():
        analysis = store.get_analysis(w["id"])
        if not analysis:
            continue
        tl = analysis.get("training_load", {})
        if not tl.get("counts_toward_planned_load", True):
            continue
        start = datetime.fromisoformat(w["start_time"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        age_days = (now - start).total_seconds() / 86400.0
        load = tl.get("load", 0.0)
        if age_days <= 28:
            load_28 += load
        if age_days <= 7:
            load_7 += load
        if latest_time is None or start > latest_time:
            latest_time = start
            last_hard = (tl.get("intensity_factor") or 0) > 0.85
    return load_7, load_28, last_hard


def create_app(db_path: str | None = None) -> FastAPI:
    dsn = db_path or os.environ.get("DATABASE_URL") or os.environ.get("COACH_DB", "data/coach.db")
    app = FastAPI(title="AI Running Coach", version="0.1.0",
                  description="Deterministic running analytics core (PRD v2.0)")

    def store():
        return open_store(dsn)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return _DASHBOARD_HTML.read_text(encoding="utf-8")

    @app.get("/health")
    def health() -> dict:
        """Liveness + DB connectivity probe (used by the deploy pipeline)."""
        with store() as s:
            s._exec("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/athlete")
    def get_athlete() -> dict:
        return ATHLETE.model_dump()

    @app.get("/workouts")
    def get_workouts() -> list[dict]:
        with store() as s:
            return s.list_workouts()

    @app.get("/workouts/{workout_id}")
    def get_workout(workout_id: str) -> dict:
        with store() as s:
            w = s.get_workout(workout_id)
            if not w:
                raise HTTPException(404, "workout not found")
            return w.model_dump(mode="json")

    @app.post("/workouts/import")
    def import_workouts(raw_dir: str = Body(..., embed=True)) -> dict:
        report = process_raw_directory(raw_dir, ATHLETE)
        workouts = report.pop("_workouts")
        body = report.pop("_body_measurements")
        with store() as s:
            for workout, analysis in workouts:
                s.upsert_workout(workout, analysis)
            s.upsert_body_measurements(body)
        return report

    @app.post("/workouts/upload")
    async def upload_workout(file: UploadFile = File(...)) -> dict:
        """Ingest a single uploaded TCX file and persist it to the store (PRD §5, §27)."""
        raw = await file.read()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("utf-8", errors="replace")
        try:
            workout = parse_tcx(content, source_file=file.filename)
        except Exception as exc:
            raise HTTPException(422, f"could not parse TCX: {exc}")
        workout.terrain = infer_terrain(workout)
        workout.session_type = classify_session(workout)
        analysis = analyse_workout(workout, ATHLETE)
        with store() as s:
            existing = s.get_workout(workout.id) is not None
            s.upsert_workout(workout, analysis)
        return {
            "status": "ok",
            "workout_id": workout.id,
            "already_existed": existing,
            "source_file": workout.source_file,
            "start_time": workout.start_time.isoformat(),
            "session_type": workout.session_type.value,
            "terrain": workout.terrain.value,
            "distance_km": round((workout.distance_m or 0) / 1000.0, 2),
            "duration_min": round((workout.duration_s or 0) / 60.0, 1),
            "avg_hr": workout.avg_hr,
        }

    @app.post("/workouts/treadmill")
    def log_treadmill(payload: TreadmillLogIn) -> dict:
        """Log or retroactively edit a treadmill session from a free-text description (PRD §15).

        No GPS is recorded, so the athlete describes the session one phase per line, e.g.
        "25 min at 4.7mph with 1%". The text is parsed into structured phases and persisted
        as a treadmill workout. Pass ``workout_id`` to overwrite an earlier session.

        Editing a session that was recorded by a device (a TCX upload) never regenerates the
        time-series: the measured trackpoints, heart rate and distance are preserved and the
        description is only stored as a note.
        """
        existing = None
        if payload.workout_id:
            with store() as s:
                existing = s.get_workout(payload.workout_id)
            if existing is None:
                raise HTTPException(404, "workout not found")

        if existing is not None and existing.source != "manual_treadmill":
            try:
                definition = parse_treadmill_log(payload.description)
            except ValueError as exc:
                raise HTTPException(422, f"could not parse treadmill description: {exc}")
            existing.notes = payload.description.strip()
            main = max(
                (p for p in definition.phases if p.speed_mph),
                key=lambda p: p.duration_min or 0.0,
                default=None,
            )
            if main is not None:
                existing.treadmill_speed_mph = main.speed_mph
                existing.treadmill_incline_pct = main.incline_pct
            analysis = analyse_workout(existing, ATHLETE)
            with store() as s:
                s.upsert_workout(existing, analysis)
            return {
                "status": "ok",
                "mode": "annotated",
                "workout_id": existing.id,
                "already_existed": True,
                "start_time": existing.start_time.isoformat(),
                "session_type": existing.session_type.value,
                "terrain": existing.terrain.value,
                "distance_km": round((existing.distance_m or 0) / 1000.0, 2),
                "duration_min": round((existing.duration_s or 0) / 60.0, 1),
                "avg_hr": existing.avg_hr,
                "phases": len([ln for ln in payload.description.splitlines() if ln.strip()]),
            }

        # New session, or edit of a manually-entered one: (re)build synthetic trackpoints.
        start_time = payload.start_time
        avg_hr = payload.avg_hr
        if existing is not None:
            if start_time is None:
                start_time = existing.start_time
            if avg_hr is None:
                avg_hr = existing.avg_hr  # keep the reported HR unless explicitly changed
        try:
            workout = build_treadmill_workout(
                payload.description, start_time=start_time, avg_hr=avg_hr
            )
        except ValueError as exc:
            raise HTTPException(422, f"could not parse treadmill description: {exc}")
        workout.terrain = infer_terrain(workout)
        workout.session_type = classify_session(workout)
        analysis = analyse_workout(workout, ATHLETE)
        with store() as s:
            already_existed = s.get_workout(workout.id) is not None
            # Retroactive edit that shifts the start time leaves a stale row behind; drop it.
            if payload.workout_id and payload.workout_id != workout.id:
                s.delete_workout(payload.workout_id)
            s.upsert_workout(workout, analysis)
        return {
            "status": "ok",
            "mode": "synthetic",
            "workout_id": workout.id,
            "already_existed": already_existed,
            "start_time": workout.start_time.isoformat(),
            "session_type": workout.session_type.value,
            "terrain": workout.terrain.value,
            "distance_km": round((workout.distance_m or 0) / 1000.0, 2),
            "duration_min": round((workout.duration_s or 0) / 60.0, 1),
            "avg_hr": workout.avg_hr,
            "phases": len([ln for ln in payload.description.splitlines() if ln.strip()]),
        }

    @app.get("/workouts/{workout_id}/analysis")
    def get_workout_analysis(workout_id: str) -> dict:
        with store() as s:
            analysis = s.get_analysis(workout_id)
            if analysis:
                return analysis
            w = s.get_workout(workout_id)
            if not w:
                raise HTTPException(404, "workout not found")
            return analyse_workout(w, ATHLETE)

    @app.get("/workouts/{workout_id}/streams")
    def get_workout_streams(workout_id: str, points: int = 400) -> dict:
        """Downsampled time-series for charting (elapsed, pace, HR, altitude)."""
        with store() as s:
            w = s.get_workout(workout_id)
            if not w:
                raise HTTPException(404, "workout not found")
        pts = w.trackpoints
        step = max(1, len(pts) // max(points, 1))
        sampled = pts[::step]
        return {
            "workout_id": w.id,
            "elapsed_s": [round(p.elapsed_s, 1) for p in sampled],
            "distance_km": [round((p.distance_m or 0) / 1000.0, 3) for p in sampled],
            "pace_s_per_km": [round(p.pace_s_per_km, 1) if p.pace_s_per_km else None for p in sampled],
            "hr_bpm": [p.hr_bpm for p in sampled],
            "altitude_m": [round(p.altitude_m, 1) if p.altitude_m is not None else None for p in sampled],
        }

    @app.get("/trends/aerobic-efficiency")
    def trend_efficiency() -> list[dict]:
        out = []
        with store() as s:
            for w in s.list_workouts():
                a = s.get_analysis(w["id"])
                if a and a.get("aerobic_efficiency", {}).get("available"):
                    out.append({"workout_id": w["id"], "start_time": w["start_time"],
                                **a["aerobic_efficiency"]})
        return out

    @app.get("/trends/hr-drift")
    def trend_drift() -> list[dict]:
        out = []
        with store() as s:
            for w in s.list_workouts():
                a = s.get_analysis(w["id"])
                if a and a.get("hr_drift", {}).get("available"):
                    out.append({"workout_id": w["id"], "start_time": w["start_time"],
                                **a["hr_drift"]})
        return out

    @app.get("/training-load")
    def training_load_summary() -> dict:
        with store() as s:
            load_7, load_28, last_hard = _recent_loads(s)
            per_workout = []
            for w in s.list_workouts():
                a = s.get_analysis(w["id"])
                if a:
                    per_workout.append({"workout_id": w["id"], "start_time": w["start_time"],
                                        **a["training_load"]})
        acwr = round(load_7 / (load_28 / 4.0), 2) if load_28 > 0 else None
        return {"load_7d": round(load_7, 1), "load_28d": round(load_28, 1),
                "acute_chronic_ratio": acwr, "last_session_hard": last_hard,
                "per_workout": per_workout}

    @app.get("/trends/body-weight")
    def trend_body() -> dict:
        with store() as s:
            return weight_trend(s.list_body_measurements())

    @app.get("/readiness")
    def get_readiness() -> dict:
        with store() as s:
            ctx = s.get_recovery(date.today())
            load_7, load_28, last_hard = _recent_loads(s)
        result = compute_readiness(ctx, ATHLETE, load_7, load_28, last_hard)
        return {"level": result.level.value, "score": result.score, "reasons": result.reasons,
                "stop_workout": result.stop_workout, "recommendation": result.recommendation,
                "inputs": result.inputs}

    @app.post("/context/recovery")
    def post_recovery(payload: RecoveryIn) -> dict:
        ctx = RecoveryContext(**payload.model_dump())
        with store() as s:
            s.upsert_recovery(ctx)
        return {"status": "ok", "for_date": ctx.for_date.isoformat()}

    @app.get("/plan")
    def get_plan() -> dict:
        return standard_treadmill_session().model_dump(mode="json")

    @app.post("/plan/generate")
    def post_plan_generate() -> dict:
        with store() as s:
            ctx = s.get_recovery(date.today())
            load_7, load_28, last_hard = _recent_loads(s)
        readiness = compute_readiness(ctx, ATHLETE, load_7, load_28, last_hard)
        plan = generate_next_session(readiness)
        return {"readiness": {"level": readiness.level.value, "score": readiness.score,
                              "reasons": readiness.reasons},
                "plan": plan.model_dump(mode="json")}

    @app.post("/plan/adapt")
    def post_plan_adapt(definition: dict = Body(...)) -> dict:
        with store() as s:
            ctx = s.get_recovery(date.today())
            load_7, load_28, last_hard = _recent_loads(s)
        readiness = compute_readiness(ctx, ATHLETE, load_7, load_28, last_hard)
        base = load_definition(definition)
        adapted = adapt_definition(base, readiness)
        return {"readiness_level": readiness.level.value,
                "adapted": adapted.model_dump(mode="json")}

    @app.post("/ai/analyse-session")
    def ai_analyse(workout_id: str = Body(..., embed=True)) -> dict:
        with store() as s:
            analysis = s.get_analysis(workout_id)
            if not analysis:
                w = s.get_workout(workout_id)
                if not w:
                    raise HTTPException(404, "workout not found")
                analysis = analyse_workout(w, ATHLETE)
        return explain_session(analysis)

    @app.post("/ai/recommend-next-session")
    def ai_recommend(workout_id: str = Body(..., embed=True)) -> dict:
        with store() as s:
            analysis = s.get_analysis(workout_id)
            if not analysis:
                raise HTTPException(404, "analysis not found")
            ctx = s.get_recovery(date.today())
            load_7, load_28, last_hard = _recent_loads(s)
        readiness = compute_readiness(ctx, ATHLETE, load_7, load_28, last_hard)
        return recommend_next_session(analysis, {"level": readiness.level.value})

    @app.get("/races")
    def get_races() -> list[dict]:
        with store() as s:
            return s.list_races()

    @app.post("/races")
    def post_race(payload: RaceIn) -> dict:
        with store() as s:
            race_id = s.add_race(payload.name, payload.race_date, payload.distance_m,
                                 payload.target_time_s, payload.verified)
        # Future race dates must be verified before treated as authoritative (PRD §16).
        return {"id": race_id, "verified": payload.verified}

    @app.get("/data-quality")
    def get_data_quality() -> dict:
        report_path = Path(os.environ.get("COACH_REPORT", "data/processed/data_quality.json"))
        if report_path.exists():
            import json
            return json.loads(report_path.read_text(encoding="utf-8"))
        with store() as s:
            workouts = s.list_workouts()
            issues = []
            for w in workouts:
                a = s.get_analysis(w["id"])
                if a:
                    issues.append({"workout_id": w["id"],
                                   "hr_suspect_fraction": a["hr_quality"]["suspect_fraction"],
                                   "data_quality": a["data_quality"]})
            return {"workouts": issues}

    @app.get("/summary")
    def get_summary() -> dict:
        """Everything the dashboard overview needs in one call."""
        with store() as s:
            workouts = s.list_workouts()
            load_7, load_28, last_hard = _recent_loads(s)
            ctx = s.get_recovery(date.today())
            body = weight_trend(s.list_body_measurements())
            session_breakdown: dict[str, int] = {}
            per_workout = []
            for w in workouts:
                session_breakdown[w["session_type"]] = session_breakdown.get(w["session_type"], 0) + 1
                a = s.get_analysis(w["id"])
                per_workout.append({
                    "id": w["id"],
                    "start_time": w["start_time"],
                    "session_type": w["session_type"],
                    "terrain": w["terrain"],
                    "distance_km": round((w["distance_m"] or 0) / 1000.0, 2),
                    "duration_min": round((w["duration_s"] or 0) / 60.0, 1),
                    "avg_hr": w["avg_hr"],
                    "avg_pace_s_per_km": w["avg_pace_s_per_km"],
                    "elevation_gain_m": w["elevation_gain_m"],
                    "load": (a or {}).get("training_load", {}).get("load") if a else None,
                    "hr_drift_pct": (a or {}).get("hr_drift", {}).get("drift_pct") if a else None,
                    "aerobic_efficiency": (a or {}).get("aerobic_efficiency", {}).get("efficiency_mps_per_bpm") if a else None,
                    "hr_suspect_fraction": (a or {}).get("hr_quality", {}).get("suspect_fraction") if a else None,
                })
        readiness = compute_readiness(ctx, ATHLETE, load_7, load_28, last_hard)
        total_distance = sum(w["distance_km"] for w in per_workout)
        total_duration = sum(w["duration_min"] for w in per_workout)
        return {
            "totals": {
                "workouts": len(per_workout),
                "distance_km": round(total_distance, 1),
                "duration_min": round(total_duration, 0),
                "duration_h": round(total_duration / 60.0, 1),
            },
            "session_breakdown": session_breakdown,
            "readiness": {"level": readiness.level.value, "score": readiness.score,
                          "reasons": readiness.reasons, "recommendation": readiness.recommendation},
            "training_load": {"load_7d": round(load_7, 1), "load_28d": round(load_28, 1),
                              "acute_chronic_ratio": round(load_7 / (load_28 / 4.0), 2) if load_28 > 0 else None},
            "body": {"latest_kg": body.get("latest_kg"), "trend_kg": body.get("trend_kg"),
                     "series": body.get("rolling_series", [])} if body.get("available") else None,
            "goal_5k_seconds": ATHLETE.goal_5k_seconds,
            "workouts": per_workout,
        }

    return app
