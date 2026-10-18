"""Informative presentation without rewriting canonical classification or guessing effort."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.analytics.analysis import analyse_workout
from app.api import create_app
from app.ingestion import build_treadmill_workout
from app.models import Athlete
from app.persistence import SqliteStore
from app.services.classification import classify_session
from app.services.session_labels import describe_session, effort_label


def test_reported_repeats_do_not_depend_on_absolute_running_speed():
    analysis = {
        "session_type": "easy", "treadmill_effort": {"available": True, "phases": [
            {"type": phase} for phase in ["warmup", "interval", "recovery"] * 3 + ["cooldown"]
        ]},
    }
    label = describe_session(analysis)
    assert label["code"] == "interval"
    assert label["label"] == "Intervals"
    assert label["source"] == "athlete_reported_structure"
    assert label["detected_type"] == "easy"
    assert "3 reported work blocks" in label["detail"]
    assert label["effort"]["rpe"] is None


@pytest.mark.parametrize(("phases", "code", "name"), [
    (["interval"], "interval", "Quality block"),
    (["warmup", "progression", "cooldown"], "progression", "Progression"),
    (["warmup", "aerobic", "cooldown"], "steady", "Steady run"),
])
def test_explicit_structure_and_reported_effort_are_separate(phases, code, name):
    analysis = {"session_type": "easy", "treadmill_effort": {
        "available": True, "phases": [{"type": phase} for phase in phases],
    }}
    label = describe_session(analysis, {"perceived_exertion": 8})
    assert (label["code"], label["label"]) == (code, name)
    assert label["effort"] == {
        "rpe": 8, "label": "Hard", "level": 4, "source": "athlete_reported",
    }


@pytest.mark.parametrize("kind", ["benchmark", "incomplete", "family_fun", "interval"])
def test_distinct_automatic_types_are_preserved_without_inventing_rpe(kind):
    label = describe_session({"session_type": kind, "metrics": {"avg_hr": 185}})
    assert label["code"] == kind
    assert label["source"] == "automatic"
    assert label["effort"]["level"] == 0
    assert label["effort"]["label"] == "Effort not logged"


def test_missing_structure_and_invalid_effort_are_explicit():
    assert describe_session({})["code"] == "unclassified"
    assert describe_session({"session_type": "easy"})["source"] == "automatic"
    for value in (0, 11):
        with pytest.raises(ValueError, match="between 1 and 10"):
            effort_label(value)


def test_summary_detail_and_local_narrative_agree_without_changing_canonical_data(tmp_path):
    db = tmp_path / "labels.db"
    workout = build_treadmill_workout(
        "10 min warmup at 4mph\n6 x (1 min interval at 6mph + 2 min recovery at 4mph)\n5 min cooldown",
        start_time=datetime(2026, 10, 17, 6, tzinfo=timezone.utc),
    )
    workout.session_type = classify_session(workout)
    analysis = analyse_workout(workout, Athlete())
    canonical = workout.session_type.value
    with SqliteStore(db) as store:
        store.upsert_workout(workout, analysis)
    client = TestClient(create_app(str(db)))
    assert client.put(f"/workouts/{workout.id}/feedback", json={
        "notes": "Six controlled repeats.", "perceived_exertion": 7,
    }).status_code == 200
    summary = client.get("/summary").json()
    label = summary["workouts"][0]["session_label"]
    assert label["code"] == "interval"
    assert label["effort"]["rpe"] == 7
    assert summary["session_breakdown"] == {canonical: 1}
    assert summary["session_label_breakdown"] == {"interval": 1}
    assert client.get(f"/workouts/{workout.id}/analysis").json()["session_label"] == label
    narrative = client.post("/ai/analyse-session", json={"workout_id": workout.id}).json()
    assert narrative["feature_snapshot"]["session_label"] == label
    assert "Intervals" in narrative["output"]["narrative"]
    with SqliteStore(db) as store:
        assert store.get_workout(workout.id).session_type.value == canonical
        assert store.get_analysis(workout.id) == analysis
