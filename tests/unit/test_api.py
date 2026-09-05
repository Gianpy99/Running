"""API tests (PRD §20)."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.api import create_app
from app.services.pipeline import process_raw_directory
from app.persistence import Store
from app.models import Athlete

from tests.conftest import REGRESSION_DIR


def _seed_client(tmp_path):
    db = tmp_path / "test.db"
    report = process_raw_directory(REGRESSION_DIR, Athlete())
    workouts = report.pop("_workouts")
    body = report.pop("_body_measurements")
    with Store(db) as s:
        for w, a in workouts:
            s.upsert_workout(w, a)
        s.upsert_body_measurements(body)
    return TestClient(create_app(str(db))), workouts


def test_athlete_and_workouts(tmp_path):
    client, workouts = _seed_client(tmp_path)
    assert client.get("/athlete").json()["age"] == 40
    listed = client.get("/workouts").json()
    assert len(listed) == len(workouts)


def test_health(tmp_path):
    client, _ = _seed_client(tmp_path)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_workout_analysis_and_readiness(tmp_path):
    client, workouts = _seed_client(tmp_path)
    wid = workouts[0][0].id
    analysis = client.get(f"/workouts/{wid}/analysis").json()
    assert analysis["workout_id"] == wid
    readiness = client.get("/readiness").json()
    assert readiness["level"] in ("green", "amber", "red")


def test_recovery_then_plan_generate_downgrades(tmp_path):
    client, _ = _seed_client(tmp_path)
    today = date.today().isoformat()
    client.post("/context/recovery", json={"for_date": today, "sleep_hours": 4.0,
                                            "leg_fatigue": 5, "subjective_energy": 1})
    plan = client.post("/plan/generate").json()
    assert plan["readiness"]["level"] in ("amber", "red")


def test_ai_analyse_session_has_provenance(tmp_path):
    client, workouts = _seed_client(tmp_path)
    wid = workouts[0][0].id
    result = client.post("/ai/analyse-session", json={"workout_id": wid}).json()
    assert "feature_snapshot_sha256" in result
    assert result["prompt_version"]
