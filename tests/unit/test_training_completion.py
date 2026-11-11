"""Completed advice is a reported workout until the watch file is attached."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.ai.context import build_context
from app.ai.schemas import CoachRequest
from app.api import create_app
from app.models import Athlete
from app.persistence import SqliteStore
from tests.unit.test_coaching import NOW, _mock_provider, _output, _saved_review


TCX = b"""<?xml version="1.0"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
<Activities><Activity Sport="Running"><Id>2026-10-18T10:00:00Z</Id>
<Lap StartTime="2026-10-18T10:00:00Z"><TotalTimeSeconds>1800</TotalTimeSeconds>
<DistanceMeters>4500</DistanceMeters><Track>
<Trackpoint><Time>2026-10-18T10:00:00Z</Time><DistanceMeters>0</DistanceMeters>
<HeartRateBpm><Value>130</Value></HeartRateBpm></Trackpoint>
<Trackpoint><Time>2026-10-18T10:30:00Z</Time><DistanceMeters>4500</DistanceMeters>
<HeartRateBpm><Value>145</Value></HeartRateBpm></Trackpoint>
</Track></Lap></Activity></Activities></TrainingCenterDatabase>"""


@pytest.fixture
def completion(tmp_path):
    path = tmp_path / "completion.db"
    review = _saved_review(0)
    review["workout_id"] = None
    with SqliteStore(path) as store:
        store.save_coach_review(review)
    return TestClient(create_app(str(path))), path, review


def _complete(client, review, **changes):
    return client.post(f"/ai/coaching/history/{review['id']}/complete", json={
        "start_time": "2026-10-18T10:00:00+00:00", "duration_min": 28,
        "setting": "outdoor", "perceived_exertion": 7, "notes": "Shortened the run; tired legs.",
        **changes,
    })


def test_completion_persists_report_and_counts_as_training_without_fake_metrics(completion):
    client, path, review = completion
    before = client.get("/ai/coaching/history").json()[0]
    assert before.get("completed_workout") is None
    response = _complete(client, review)
    assert response.status_code == 200, response.text
    wid = response.json()["completed_workout"]["workout_id"]
    assert response.json()["completed_workout"]["awaiting_tcx"] is True
    assert client.get("/workouts").json()[0]["source"] == "manual_completed"
    summary = client.get("/summary").json()
    assert summary["totals"]["workouts"] == 1
    assert summary["totals"]["duration_min"] == 28
    assert summary["workouts"][0]["session_label"]["effort"]["rpe"] == 7
    assert summary["workouts"][0]["awaiting_tcx"] is True
    with SqliteStore(path) as store:
        workout = store.get_workout(wid)
        assert workout.trackpoints == []
        assert workout.coaching_review_id == review["id"]
        assert workout.reported_setting == "outdoor"
        assert workout.avg_hr is None and workout.avg_pace_s_per_km is None
        assert store.get_analysis(wid)["training_load"]["method"] == "rpe_weighted"
        assert store.get_analysis(wid)["terrain"] == "unknown"
        context = build_context(store, CoachRequest(purpose="next_training"), Athlete(), NOW)
        selected = context["selected_session"]
        assert selected["features"]["distance_km"] is None
        assert selected["athlete_feedback"]["perceived_exertion"] == 7
        assert selected["recording"]["awaiting_tcx"] is True
        assert sum(week["sessions"] for week in context["weekly_training"]) == 1
        assert store.get_coach_review(review["id"]) == review
    repeated = _complete(client, review, perceived_exertion=3)
    assert repeated.status_code == 200
    assert len(client.get("/workouts").json()) == 1
    assert client.get(f"/workouts/{wid}/feedback").json()["feedback"]["perceived_exertion"] == 7
    assert client.get(f"/ai/coaching/history/{review['id']}").json()["completed_workout"]["workout_id"] == wid


@pytest.mark.parametrize("explicit", [False, True])
def test_tcx_attachment_and_reupload_keep_identity_feedback_and_saved_reviews(completion, explicit):
    client, path, review = completion
    wid = _complete(client, review).json()["completed_workout"]["workout_id"]
    feedback_review = _saved_review(1, kind="workout_feedback")
    feedback_review["workout_id"] = wid
    with SqliteStore(path) as store:
        store.save_coach_review(feedback_review)
    assert client.put(f"/workouts/{wid}/feedback", json={
        "perceived_exertion": 8, "notes": "Updated report before attaching.",
    }).status_code == 200
    for _ in range(2):
        response = client.post("/workouts/upload", files={"file": ("run.tcx", TCX, "application/xml")},
                               data={"workout_id": wid} if explicit else {})
        assert response.status_code == 200, response.text
        assert response.json()["workout_id"] == wid
        assert response.json()["attached_to_report"] is True
        assert len(client.get("/workouts").json()) == 1
    with SqliteStore(path) as store:
        workout = store.get_workout(wid)
        assert workout.source == "tcx" and workout.source_file == "run.tcx"
        assert workout.distance_m == 4500 and workout.duration_s == 1800
        assert len(workout.trackpoints) == 2
        assert workout.notes == "Shortened the run; tired legs."
        assert workout.terrain.value == "unknown"  # Outdoor report without GPS is not a treadmill run.
        assert workout.reported_rpe == 8
        assert store.get_workout_feedback(wid)["perceived_exertion"] == 8
        assert store.get_workout_feedback(wid)["notes"] == "Updated report before attaching."
        assert store.get_coach_review(feedback_review["id"])["workout_id"] == wid
    saved = client.get(f"/ai/coaching/history/{review['id']}").json()
    assert saved["completed_workout"]["awaiting_tcx"] is False
    assert client.get("/summary").json()["workouts"][0]["awaiting_tcx"] is False
    assert _complete(client, review).json()["completed_workout"]["awaiting_tcx"] is False


def test_explicit_attachment_can_correct_a_reported_start_time(completion):
    client, _, review = completion
    wid = _complete(client, review, start_time="2026-10-18T09:00:00Z").json()["completed_workout"]["workout_id"]
    response = client.post("/workouts/upload", data={"workout_id": wid},
                           files={"file": ("run.tcx", TCX, "application/xml")})
    assert response.status_code == 200
    assert len(client.get("/workouts").json()) == 1
    assert client.get(f"/workouts/{wid}").json()["start_time"] == "2026-10-18T10:00:00Z"


@pytest.mark.parametrize("changes", [
    {"start_time": "2026-10-18T10:00:00"},
    {"start_time": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
    {"duration_min": 0}, {"perceived_exertion": 11}, {"setting": "either"},
])
def test_invalid_completion_is_explicit_and_does_not_create_a_workout(completion, changes):
    client, _, review = completion
    assert _complete(client, review, **changes).status_code == 422
    assert client.get("/workouts").json() == []


@pytest.mark.parametrize("action", ["rest", "ask", "feedback"])
def test_non_running_advice_cannot_be_completed(completion, action):
    client, path, review = completion
    if action == "feedback":
        review["kind"] = "workout_feedback"
        review["output"]["next_session"] = None
    else:
        review["output"]["next_session"]["action"] = action
    review["id"] = "non-running-" + action
    with SqliteStore(path) as store:
        store.save_coach_review(review)
    assert _complete(client, review).status_code == 422
    assert client.get("/workouts").json() == []


def test_missing_advice_and_invalid_tcx_preserve_reports(completion):
    client, _, review = completion
    assert _complete(client, {"id": "missing"}).status_code == 404
    wid = _complete(client, review).json()["completed_workout"]["workout_id"]
    response = client.post("/workouts/upload", data={"workout_id": wid},
                           files={"file": ("bad.tcx", b"not XML", "application/xml")})
    assert response.status_code == 422
    assert client.get(f"/workouts/{wid}").json()["source"] == "manual_completed"


def test_feedback_generation_on_completed_run_remains_cached_after_saving_new_rpe(completion, monkeypatch):
    from app.api import routes

    client, _, review = completion
    wid = _complete(client, review).json()["completed_workout"]["workout_id"]
    original = routes.build_context
    monkeypatch.setattr(routes, "build_context", lambda s, payload, athlete: original(s, payload, athlete, NOW))
    calls = _mock_provider(monkeypatch, _output("workout_feedback"))
    payload = {"purpose": "workout_feedback", "workout_id": wid,
               "perceived_exertion": 8, "notes": "Updated athlete feedback."}
    preview = client.post("/ai/coaching/preview", json=payload).json()
    payload["preview_hash"] = preview["context_sha256"]
    first = client.post("/ai/coaching/generate", json=payload)
    assert first.status_code == 200, first.text
    repeated = client.post("/ai/coaching/generate", json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["cached"] is True
    assert len(calls) == 1


def test_estimated_start_still_attaches_tcx_to_pending_run(completion):
    client, path, review = completion
    wid = _complete(client, review, start_time="2026-10-18T11:05:00+00:00").json()["completed_workout"]["workout_id"]
    response = client.post("/workouts/upload", files={"file": ("run.tcx", TCX, "application/xml")})
    assert response.status_code == 200, response.text
    assert response.json()["workout_id"] == wid
    assert len(client.get("/workouts").json()) == 1


def test_treadmill_completion_stores_phases_instead_of_default_routine(completion):
    client, path, review = completion
    response = _complete(client, review, setting="treadmill",
                         treadmill_description="5 min warmup at 4.0mph\n20 min at 6.2mph with 1%\n3 min cooldown at 3.5mph")
    assert response.status_code == 200, response.text
    wid = response.json()["completed_workout"]["workout_id"]
    with SqliteStore(path) as store:
        workout = store.get_workout(wid)
        assert workout.treadmill_speed_mph == 6.2
        assert "20 min at 6.2mph" in workout.notes
    assert client.get(f"/workouts/{wid}/feedback").json()["feedback"]["notes"] == "Shortened the run; tired legs."
    client.post("/workouts/upload", files={"file": ("run.tcx", TCX, "application/xml")})
    with SqliteStore(path) as store:
        workout = store.get_workout(wid)
        assert "20 min at 6.2mph" in workout.notes
        from app.analytics.mainset import main_set_window
        assert main_set_window(workout, Athlete())["method"] == "declared"
