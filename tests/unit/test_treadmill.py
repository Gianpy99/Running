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


def test_manual_session_not_flagged_suspect():
    from app.analytics.quality import annotate_hr_quality

    workout = build_treadmill_workout("30 min at 5mph", avg_hr=140)
    result = annotate_hr_quality(workout)
    # A self-reported session has no sensor stream, so nothing is flagged as suspect.
    assert result.suspect_fraction == 0.0


def test_edit_manual_preserves_reported_hr(tmp_path):
    client = TestClient(create_app(str(tmp_path / "t.db")))
    created = client.post(
        "/workouts/treadmill",
        json={"description": "20 min at 5mph", "start_time": "2026-06-01T07:00:00", "avg_hr": 135},
    ).json()
    wid = created["workout_id"]
    # Re-saving without an HR must not wipe the previously reported HR.
    edited = client.post(
        "/workouts/treadmill",
        json={"description": "25 min at 5mph", "workout_id": wid},
    ).json()
    assert edited["mode"] == "synthetic"
    assert edited["avg_hr"] == 135


def test_edit_device_recorded_preserves_measurements(tmp_path):
    from datetime import timedelta

    from app.analytics.analysis import analyse_workout
    from app.analytics.terrain import infer_terrain
    from app.models import Athlete, Trackpoint, Workout
    from app.persistence import Store

    db = tmp_path / "t.db"
    start = datetime(2026, 5, 1, 6, 0, tzinfo=timezone.utc)
    pts = [
        Trackpoint(
            timestamp=start + timedelta(seconds=i * 10),
            elapsed_s=i * 10,
            distance_m=i * 30,
            speed_mps=3.0,
            hr_bpm=120 + (i % 20),
        )
        for i in range(60)
    ]
    watch = Workout(
        id=start.strftime("%Y%m%dT%H%M%S"),
        source="tcx",
        source_file="run.tcx",
        start_time=start,
        duration_s=600,
        distance_m=1800,
        trackpoints=pts,
    )
    watch.terrain = infer_terrain(watch)
    analysis = analyse_workout(watch, Athlete())
    with Store(db) as s:
        s.upsert_workout(watch, analysis)
    measured_hr = watch.avg_hr
    assert measured_hr is not None

    client = TestClient(create_app(str(db)))
    resp = client.post(
        "/workouts/treadmill",
        json={"description": "10 min at 4mph\n5 min cooldown", "workout_id": watch.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "annotated"
    assert body["avg_hr"] == measured_hr  # measured HR untouched

    detail = client.get(f"/workouts/{watch.id}").json()
    assert detail["source"] == "tcx"  # still a device recording
    assert detail["notes"] == "10 min at 4mph\n5 min cooldown"
    assert len(detail["trackpoints"]) == 60  # measured stream intact


def test_treadmill_effort_incline_matters():
    from app.analytics.terrain import treadmill_effort

    start = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)
    one_pct = treadmill_effort(build_treadmill_workout("30 min at 4.7mph with 1%", start_time=start))
    two_pct = treadmill_effort(build_treadmill_workout("30 min at 4.7mph with 2%", start_time=start))
    assert one_pct["available"] and two_pct["available"]
    # Same speed, more incline -> harder -> a faster equivalent-flat pace and more added effort.
    assert two_pct["incline_effort_pct"] > one_pct["incline_effort_pct"]
    assert two_pct["equivalent_flat_pace_s_per_km"] < one_pct["equivalent_flat_pace_s_per_km"]
    assert two_pct["avg_incline_pct"] == 2.0


def test_analysis_and_narrative_include_treadmill_effort():
    from app.ai import explain_session
    from app.analytics.analysis import analyse_workout
    from app.analytics.terrain import infer_terrain
    from app.models import Athlete
    from app.services.classification import classify_session

    workout = build_treadmill_workout("25 min at 4.7mph with 1%", avg_hr=140)
    workout.terrain = infer_terrain(workout)
    workout.session_type = classify_session(workout)
    analysis = analyse_workout(workout, Athlete())
    assert analysis["treadmill_effort"]["available"]
    narrative = explain_session(analysis)["output"]["narrative"]
    assert "incline" in narrative.lower()


def test_upload_replaces_near_duplicate(tmp_path):
    from datetime import timedelta

    from app.analytics.analysis import analyse_workout
    from app.analytics.terrain import infer_terrain
    from app.models import Athlete, Trackpoint, Workout
    from app.persistence import Store

    db = tmp_path / "t.db"
    # A stale session whose id drifted by 3 seconds (an earlier edit truncated the seconds).
    start = datetime(2026, 9, 6, 6, 29, 0, tzinfo=timezone.utc)
    stale = Workout(id="20260906T062900", source="manual_treadmill", start_time=start,
                    duration_s=600, distance_m=1000,
                    trackpoints=[Trackpoint(timestamp=start, elapsed_s=0, distance_m=0)])
    stale.terrain = infer_terrain(stale)
    with Store(db) as s:
        s.upsert_workout(stale, analyse_workout(stale, Athlete()))

    real_start = start + timedelta(seconds=3)
    real = Workout(id="20260906T062903", source="tcx", start_time=real_start,
                   duration_s=605, distance_m=1010,
                   trackpoints=[Trackpoint(timestamp=real_start, elapsed_s=0, distance_m=0)])
    with Store(db) as s:
        removed = s.delete_near_duplicates(real.start_time, real.id)
        s.upsert_workout(real, analyse_workout(real, Athlete()))
        remaining = [w["id"] for w in s.list_workouts()]
    assert removed == ["20260906T062900"]
    assert remaining == ["20260906T062903"]


def test_delete_workout_endpoint(tmp_path):
    client = TestClient(create_app(str(tmp_path / "t.db")))
    created = client.post(
        "/workouts/treadmill",
        json={"description": "20 min at 5mph", "start_time": "2026-08-01T07:00:00"},
    ).json()
    wid = created["workout_id"]
    assert client.delete(f"/workouts/{wid}").status_code == 200
    assert client.get(f"/workouts/{wid}").status_code == 404
    assert client.delete(f"/workouts/{wid}").status_code == 404


def test_main_set_uses_the_declared_warmup_and_cooldown():
    """The athlete typed the phases, so the window is exact, not inferred from pace."""
    from app.analytics.mainset import main_set_window

    workout = build_treadmill_workout(SAMPLE, avg_hr=145)
    window = main_set_window(workout)
    assert window["available"] is True
    assert window["method"] == "declared"
    # 10 min warmup, then 30 min of work, then a 5 min cooldown, to the second.
    assert window["start_s"] == 600.0
    assert window["end_s"] == 2400.0
    assert window["warmup_s"] == 600.0
    assert window["cooldown_s"] == 300.0


def test_main_set_pace_excludes_the_slow_warmup_and_cooldown():
    from app.analytics.analysis import main_set_metrics
    from app.analytics.metrics import basic_metrics

    workout = build_treadmill_workout(SAMPLE, avg_hr=145)
    whole, main = basic_metrics(workout), main_set_metrics(workout)
    # Work is 25 min @ 4.7 mph + 5 min @ 5.0 mph -> 4.75 mph average -> ~7:51/km.
    assert main["avg_pace_s_per_km"] == pytest.approx(471, abs=5)
    # The easy warmup and ramp-down cooldown cost ~40 s/km on the session average.
    assert whole["avg_pace_s_per_km"] - main["avg_pace_s_per_km"] > 30
    assert main["duration_s"] == 1800.0


