"""Treadmill free-text logging tests (PRD §15)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.ingestion import build_treadmill_workout, parse_treadmill_log
from app.models.enums import PhaseType, TerrainType

SAMPLE = """10 min warmup at 4mph
25 min at 4.7mph with 1%
5 min at 5mph with 1%
5 min cooldown"""


def test_parse_phases():
    definition = parse_treadmill_log(SAMPLE)
    assert [p.type for p in definition.phases] == [
        PhaseType.WARMUP,
        PhaseType.AEROBIC,
        PhaseType.AEROBIC,
        PhaseType.COOLDOWN,
    ]
    assert definition.total_duration_min == 45
    warm, aerobic, prog, cool = definition.phases
    assert warm.speed_mph == 4.0 and warm.incline_pct is None
    assert aerobic.speed_mph == 4.7 and aerobic.incline_pct == 1
    assert prog.speed_mph == 5.0
    assert cool.speed_mph is None


def test_parse_kmh_and_units():
    definition = parse_treadmill_log("30 minutes at 8 km/h with 2%")
    phase = definition.phases[0]
    assert phase.duration_min == 30
    assert phase.speed_mph == pytest.approx(4.97, abs=0.02)
    assert phase.incline_pct == 2


def test_parse_requires_duration():
    with pytest.raises(ValueError):
        parse_treadmill_log("just running at 5mph")


def test_build_workout_totals():
    start = datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc)
    workout = build_treadmill_workout(SAMPLE, start_time=start, avg_hr=140)
    assert workout.source == "manual_treadmill"
    assert workout.duration_s == 45 * 60
    assert workout.avg_hr == 140
    assert workout.notes == SAMPLE
    # Main effort = longest phase with a speed (25 min @ 4.7 mph, 1%).
    assert workout.treadmill_speed_mph == 4.7
    assert workout.treadmill_incline_pct == 1
    # Running phases plus a cooldown that ramps 5 mph down to a stop over 5 minutes.
    mps = 0.44704
    running_m = (10 * 4.0 + 25 * 4.7 + 5 * 5.0) * 60 * mps
    cooldown_m = (4 + 3 + 2 + 1 + 0) * 60 * mps
    assert workout.distance_m == pytest.approx(running_m + cooldown_m, rel=0.02)
    assert not any(p.latitude is not None for p in workout.trackpoints)


def test_cooldown_ramps_down_from_previous_speed():
    start = datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc)
    workout = build_treadmill_workout("5 min at 5mph\n5 min cooldown", start_time=start)
    # gap = 5 / 5 = 1 mph per minute; cooldown minute speeds are 4, 3, 2, 1, then a stop.
    mph = lambda p: round((p.speed_mps or 0) / 0.44704, 1)
    minute = lambda m: next(p for p in workout.trackpoints if abs(p.elapsed_s - (300 + m * 60)) < 1)
    assert mph(minute(0)) == 4.0
    assert mph(minute(1)) == 3.0
    assert mph(minute(4)) == 0.0


def test_edit_treadmill_overwrites(tmp_path):
    client = TestClient(create_app(str(tmp_path / "t.db")))
    created = client.post(
        "/workouts/treadmill",
        json={"description": "20 min at 5mph", "start_time": "2026-03-01T07:00:00"},
    ).json()
    wid = created["workout_id"]
    edited = client.post(
        "/workouts/treadmill",
        json={"description": "30 min at 6mph", "workout_id": wid},
    )
    assert edited.status_code == 200, edited.text
    # Same start time reused -> same id, still a single stored session.
    assert edited.json()["workout_id"] == wid
    assert len(client.get("/workouts").json()) == 1
    assert client.get(f"/workouts/{wid}").json()["notes"] == "30 min at 6mph"


def test_api_log_treadmill(tmp_path):
    client = TestClient(create_app(str(tmp_path / "t.db")))
    resp = client.post(
        "/workouts/treadmill",
        json={"description": SAMPLE, "start_time": "2026-01-02T07:00:00", "avg_hr": 140},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["terrain"] == TerrainType.TREADMILL.value
    assert body["duration_min"] == 45.0
    assert body["avg_hr"] == 140

    listed = client.get("/workouts").json()
    assert len(listed) == 1
    detail = client.get(f"/workouts/{body['workout_id']}").json()
    assert detail["notes"] == SAMPLE


def test_api_rejects_bad_description(tmp_path):
    client = TestClient(create_app(str(tmp_path / "t.db")))
    resp = client.post("/workouts/treadmill", json={"description": "no phases here"})
    assert resp.status_code == 422
