"""Treadmill free-text logging tests (PRD §15)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.ingestion import build_treadmill_workout, parse_treadmill_blocks, parse_treadmill_log
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
    # Running phases plus the standard cooldown walk-down ramp.
    mps = 0.44704
    running_m = (10 * 4.0 + 25 * 4.7 + 5 * 5.0) * 60 * mps
    cooldown_m = (4.5 + 4.0 + 3.5 + 3.0 + 2.5) * 60 * mps
    assert workout.distance_m == pytest.approx(running_m + cooldown_m, rel=0.02)
    assert not any(p.latitude is not None for p in workout.trackpoints)


def test_cooldown_follows_standard_ramp():
    start = datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc)
    workout = build_treadmill_workout("5 min at 5mph\n5 min cooldown", start_time=start)
    # The walk-down is always the same, so it does not depend on the preceding speed.
    mph = lambda p: round((p.speed_mps or 0) / 0.44704, 1)
    minute = lambda m: next(p for p in workout.trackpoints if abs(p.elapsed_s - (300 + m * 60)) < 1)
    assert [mph(minute(m)) for m in range(5)] == [4.5, 4.0, 3.5, 3.0, 2.5]


def test_cooldown_ramp_is_independent_of_previous_phase():
    slow = build_treadmill_workout("5 min at 4mph\n5 min cooldown")
    fast = build_treadmill_workout("5 min at 6mph\n5 min cooldown")
    tail = lambda w: [round((p.speed_mps or 0) / 0.44704, 1)
                      for p in w.trackpoints if p.elapsed_s >= 300]
    assert tail(slow) == tail(fast)


def test_parse_repeat_block():
    blocks = parse_treadmill_blocks(
        "10 min warmup at 4mph\n"
        "6 x (1 min interval at 6mph with 1% + 2 min recovery at 4mph)\n"
        "5 min cooldown"
    )
    assert [reps for reps, _ in blocks] == [1, 6, 1]
    work, easy = blocks[1][1]
    assert work.type == PhaseType.INTERVAL
    assert work.duration_min == 1 and work.speed_mph == 6.0 and work.incline_pct == 1
    assert easy.type == PhaseType.RECOVERY
    assert easy.duration_min == 2 and easy.speed_mph == 4.0

    # Flattening expands the block: 1 warmup + 6 rounds of 2 phases + 1 cooldown.
    definition = parse_treadmill_log(
        "10 min warmup at 4mph\n"
        "6 x (1 min interval at 6mph with 1% + 2 min recovery at 4mph)\n"
        "5 min cooldown"
    )
    assert len(definition.phases) == 14
    assert definition.total_duration_min == 10 + 6 * 3 + 5


def test_repeat_phases_are_independent_copies():
    definition = parse_treadmill_log("3 x (2 min interval at 6mph)")
    assert len(definition.phases) == 3
    definition.phases[0].speed_mph = 9.9
    assert [p.speed_mph for p in definition.phases] == [9.9, 6.0, 6.0]


def test_repeat_block_separators_and_symbols():
    for text in ("4 x (1 min at 6mph + 1 min at 4mph)",
                 "4 × (1 min at 6mph, 1 min at 4mph)",
                 "4x(1 min at 6mph + 1 min at 4mph)"):
        assert parse_treadmill_blocks(text)[0][0] == 4
        assert len(parse_treadmill_blocks(text)[0][1]) == 2


def test_repeat_block_rejects_phase_without_duration():
    with pytest.raises(ValueError):
        parse_treadmill_log("5 x (1 min at 6mph + just jogging)")


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


def test_api_parse_returns_flat_phases_and_blocks(tmp_path):
    client = TestClient(create_app(str(tmp_path / "t.db")))
    resp = client.post(
        "/workouts/treadmill/parse",
        json={"description": "10 min warmup at 4mph with 1%\n"
                             "6 x (1 min interval at 6mph + 2 min recovery at 4mph)\n"
                             "5 min cooldown"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Flat view drives the analytics; the grouped view drives the dashboard's form.
    assert len(body["phases"]) == 14
    assert [b["repeat"] for b in body["blocks"]] == [1, 6, 1]
    assert [p["type"] for p in body["blocks"][1]["phases"]] == ["interval", "recovery"]
    # A cooldown with no speed stays empty, so the standard ramp is applied downstream.
    assert body["blocks"][2]["phases"][0]["speed_mph"] is None


def test_api_parse_rejects_bad_description_and_stores_nothing(tmp_path):
    client = TestClient(create_app(str(tmp_path / "t.db")))
    assert client.post("/workouts/treadmill/parse",
                       json={"description": "no phases here"}).status_code == 422
    assert client.get("/workouts").json() == []


def test_repeat_session_round_trips_through_the_api(tmp_path):
    """What the dashboard's phase builder writes must parse back to the same blocks."""
    client = TestClient(create_app(str(tmp_path / "t.db")))
    description = ("10 min warmup at 4mph with 1%\n"
                   "8 x (1 min interval at 6.5mph with 1% + 90 sec recovery at 4mph with 1%)\n"
                   "5 min cooldown with 0%")
    saved = client.post("/workouts/treadmill",
                        json={"description": description,
                              "start_time": "2026-04-01T07:00:00"})
    assert saved.status_code == 200, saved.text
    stored = client.get(f"/workouts/{saved.json()['workout_id']}").json()["notes"]
    assert stored == description
    blocks = client.post("/workouts/treadmill/parse",
                         json={"description": stored}).json()["blocks"]
    assert [b["repeat"] for b in blocks] == [1, 8, 1]
    assert blocks[1]["phases"][1]["duration_min"] == pytest.approx(1.5)


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
    """The athlete typed the phases, so the window is exact, not assumed from habit."""
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


def test_declared_description_overrides_the_habitual_default():
    """"30 min at 5mph" says there was no warmup, so none is assumed."""
    from app.analytics.mainset import main_set_window

    window = main_set_window(build_treadmill_workout("30 min at 5mph"))
    assert window["available"] is False
    assert window["reason"] == "no_warmup_or_cooldown"
    assert window["method"] == "declared"


def test_main_set_pace_excludes_the_slow_warmup_and_cooldown():
    from app.analytics.mainset import main_set_metrics
    from app.analytics.metrics import basic_metrics

    workout = build_treadmill_workout(SAMPLE, avg_hr=145)
    whole, main = basic_metrics(workout), main_set_metrics(workout)
    # Work is 25 min @ 4.7 mph + 5 min @ 5.0 mph -> 4.75 mph average -> ~7:51/km.
    assert main["avg_pace_s_per_km"] == pytest.approx(471, abs=5)
    # The easy warmup and ramp-down cooldown cost ~40 s/km on the session average.
    assert whole["avg_pace_s_per_km"] - main["avg_pace_s_per_km"] > 30
    assert main["duration_s"] == 1800.0


def test_main_set_pace_when_the_export_records_heart_rate_only():
    """Treadmill TCX files often carry one lap total and no per-point distance at all.

    The session average still works out as total/total, but the split does not, so the
    habitual easy ends are priced from their speeds and taken off the measured total.
    """
    from datetime import timedelta

    from app.analytics.mainset import main_set_metrics
    from app.models import Athlete, Trackpoint, Workout

    start = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)
    total_s, total_m = 2775.0, 6235.557
    workout = Workout(
        id="hr-only", source="tcx", start_time=start, duration_s=total_s, distance_m=total_m,
        trackpoints=[
            Trackpoint(timestamp=start + timedelta(seconds=t), elapsed_s=float(t),
                       distance_m=0.0, speed_mps=0.0, hr_bpm=150)
            for t in range(0, int(total_s) + 1, 5)
        ],
    )
    main = main_set_metrics(workout, Athlete())
    assert main["method"] == "athlete_default"
    assert main["pace_source"] == "session_total_minus_easy_ends"
    # 10 min at 4 mph = 1072.9 m; the 4.5/4/3.5/3/2.5 mph cooldown = 469.4 m.
    assert main["warmup_m"] == pytest.approx(1072.9, abs=0.5)
    assert main["cooldown_m"] == pytest.approx(469.4, abs=0.5)
    assert main["distance_m"] == pytest.approx(total_m - 1542.3, abs=1.0)
    assert main["duration_s"] == total_s - 900.0


def test_pace_stays_unavailable_when_nothing_can_support_it():
    """No distance recorded and no speeds to price the easy ends: report it, don't guess."""
    from datetime import timedelta

    from app.analytics.mainset import main_set_metrics
    from app.models import Athlete, Trackpoint, Workout

    start = datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc)
    workout = Workout(
        id="no-distance", source="tcx", start_time=start, duration_s=2400.0, distance_m=0.0,
        trackpoints=[
            Trackpoint(timestamp=start + timedelta(seconds=t), elapsed_s=float(t),
                       distance_m=0.0, speed_mps=0.0, hr_bpm=150)
            for t in range(0, 2401, 5)
        ],
    )
    main = main_set_metrics(workout, Athlete())
    assert main["available"] is True
    assert main["avg_pace_s_per_km"] is None
    assert main["pace_reason"] == "no_distance_recorded"
    assert main["avg_hr"] == 150  # heart rate is measured, so it is still reported


