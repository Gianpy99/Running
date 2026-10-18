"""Coaching stays dated, opt-in, reproducible, and separate from local execution."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai import provider
from app.ai.context import INSTRUCTIONS, build_context, context_hash
from app.ai.schemas import CoachOutput, CoachRequest, CoachingProfile
from app.api import create_app
from app.api import routes
from app.models import Athlete, RecoveryContext, Workout
from app.persistence import SqliteStore

NOW = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)


def _workout(store, wid, days_ago=0):
    workout = Workout(
        id=wid, start_time=NOW - timedelta(days=days_ago),
        duration_s=1800, distance_m=5000, notes="Reported run, not a device command.",
    )
    store.upsert_workout(workout, {
        "workout_id": wid, "analysis_version": 3,
        "metrics": {"distance_m": 5000, "duration_s": 1800, "avg_hr": 140,
                    "avg_pace_s_per_km": 360},
        "training_load": {"load": 25, "intensity_factor": 0.7,
                          "counts_toward_planned_load": True},
        "hr_quality": {"suspect_fraction": 0.25},
        "data_quality": {"has_gps": False},
    })


@pytest.fixture
def store(tmp_path):
    with SqliteStore(tmp_path / "coach.db") as store:
        _workout(store, "old", 20)
        _workout(store, "latest", 0)
        _workout(store, "future", -2)
        yield store


@pytest.fixture
def client(store, monkeypatch):
    original = routes.build_context
    monkeypatch.setattr(routes, "build_context",
                        lambda s, payload, athlete: original(s, payload, athlete, NOW))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    return TestClient(create_app(store.path))


def _context(store, purpose="next_training", **kwargs):
    request = CoachRequest(purpose=purpose, **kwargs)
    return build_context(store, request, Athlete(), NOW)


def _output(purpose="next_training", action="easy", duration=30):
    return {
        "analysis": "Evidence-based feedback with HR quality caveats.",
        "observations": ["The main set and total session differ."],
        "race_implications": ["Race year and priorities must be confirmed."],
        "next_session": None if purpose == "workout_feedback" else {
            "action": action, "date": "2026-10-19", "title": "Easy aerobic",
            "rationale": "Keep it comfortable and recheck recovery.",
            "duration_min": duration if action not in ("rest", "ask") else 0,
            "steps": ([{"phase": "easy", "duration_min": duration, "target": "Talk test"}]
                      if action not in ("rest", "ask") else []),
        },
        "uncertainties": ["Recovery may change before the run."], "questions": [],
    }


def _mock_provider(monkeypatch, output=None, status=200, payload=None, timeout=False):
    calls = []
    original = httpx.Client

    def handler(request):
        calls.append(request)
        if timeout:
            raise httpx.ReadTimeout("simulated timeout", request=request)
        data = payload if payload is not None else {
            "id": "resp-test", "status": "completed", "model": "gpt-5-mini-test",
            "usage": {"input_tokens": 100, "output_tokens": 80},
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(output or _output())}
            ]}],
        }
        return httpx.Response(status, json=data)

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-secret-never-export")
    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs:
                        original(transport=httpx.MockTransport(handler), **kwargs))
    return calls


def test_two_workflows_have_different_evidence_cutoffs(store):
    feedback = _context(store, "workout_feedback", workout_id="old", perceived_exertion=8)
    preparation = _context(store)
    assert [s["workout_id"] for s in feedback["recent_sessions"]] == ["old"]
    assert [s["workout_id"] for s in preparation["recent_sessions"]] == ["old", "latest"]
    assert feedback["next_session_date"] is None
    assert feedback["current_recovery"] is None
    assert feedback["check_in"]["perceived_exertion"] == 8
    assert preparation["next_session_date"] == "2026-10-19"
    assert preparation["history_coverage"]["later_workouts_excluded"] == 1
    assert preparation["selected_session"]["features"]["hr_suspect_fraction"] == 0.25


def test_context_changes_with_local_date_and_not_clock_seconds(store):
    request = CoachRequest(purpose="next_training")
    first = build_context(store, request, Athlete(), NOW)
    later = build_context(store, request, Athlete(), NOW + timedelta(seconds=10))
    tomorrow = build_context(store, request, Athlete(), NOW + timedelta(days=1))
    assert context_hash(first) == context_hash(later)
    assert first["as_of_date"] != tomorrow["as_of_date"]
    assert tomorrow["next_session_date"] == "2026-10-20"
    store.save_coaching_profile(CoachingProfile(timezone="Pacific/Auckland").model_dump(mode="json"))
    local = build_context(store, request, Athlete(), NOW)
    assert local["as_of_date"] == "2026-10-19"


def test_recent_history_is_bounded_and_weekly_totals_are_not_truncated(store):
    for index in range(30):
        _workout(store, f"run-{index}", index + 1)
    context = _context(store)
    assert len(context["recent_sessions"]) == 21
    assert context["history_coverage"]["recent_sessions_total"] == 32
    assert sum(week["sessions"] for week in context["weekly_training"]) == 32


def test_load_windows_use_calendar_day_boundaries_and_exclude_future_training(store):
    for age in (6, 7, 27, 28, 83, 84):
        _workout(store, f"boundary-{age}", age)
    context = _context(store)
    inputs = context["safety"]["readiness"]["inputs"]
    assert inputs["recent_load_7d"] == 50
    assert inputs["recent_load_28d"] == 125
    assert sum(week["sessions"] for week in context["weekly_training"]) == 7


def test_confirmed_profile_and_races_are_dynamic(store):
    store.save_coaching_profile(CoachingProfile(
        goals="A realistic sub-25 5k", planning_horizon=date(2027, 7, 31),
    ).model_dump(mode="json"))
    store.add_race("July main race", "2027-07-04", 5000, 1500, True)
    store.add_race("After horizon", "2027-08-01", 10000, None)
    store.add_race("Undated race", None, None, None)
    store.add_race("Legacy bad date", "July", None, None)
    context = _context(store)
    assert context["profile"]["goals"] == "A realistic sub-25 5k"
    assert "goal_5k_seconds" not in json.dumps(context)
    assert context["races_beyond_planning_horizon"] == 1
    assert len(context["races"]) == 3
    july = next(r for r in context["races"] if r["name"] == "July main race")
    assert july["days_from_today"] == (date(2027, 7, 4) - NOW.date()).days
    assert july["verified"] is True
    assert any(r["date_status"] == "missing_or_invalid" for r in context["races"])


def test_expired_horizon_is_flagged_without_guessing_next_july(store):
    store.save_coaching_profile(CoachingProfile(
        planning_horizon=date(2026, 7, 31),
    ).model_dump(mode="json"))
    context = _context(store)
    assert context["planning_horizon_status"] == "past"
    assert context["profile"]["planning_horizon"] == "2026-07-31"


def test_race_count_limit_is_explicit_not_silent_truncation(store):
    for index in range(100):
        store.add_race(f"Race {index}", None, None, None)
    assert len(_context(store)["races"]) == 100
    store.add_race("One too many", None, None, None)
    with pytest.raises(ValueError, match="More than 100"):
        _context(store)


def test_recovery_is_current_partial_and_conservative(store):
    store.upsert_recovery(RecoveryContext(
        for_date=date(2026, 10, 17), subjective_energy=5, leg_fatigue=1,
    ))
    unknown = _context(store)
    assert unknown["current_recovery"] is None
    assert "train" not in unknown["safety"]["allowed_actions"]
    known = _context(store, illness=False, concerning_pain=False,
                     subjective_energy=5, leg_fatigue=1)
    assert "train" in known["safety"]["allowed_actions"]
    pain = _context(store, concerning_pain=True)
    assert pain["safety"]["readiness"]["stop_workout"] is True
    assert pain["safety"]["allowed_actions"] == ["rest", "ask"]
    illness = _context(store, illness=True)
    assert illness["safety"]["allowed_actions"] == ["rest", "ask"]


def test_missing_history_is_supported_for_preparation(tmp_path):
    with SqliteStore(tmp_path / "empty.db") as store:
        context = _context(store)
        assert context["selected_session"] is None
        assert context["recent_sessions"] == []
        assert "train" not in context["safety"]["allowed_actions"]


@pytest.mark.parametrize("values", [
    {}, {"purpose": "workout_feedback"}, {"purpose": "next_training", "sleep_hours": 25},
    {"purpose": "next_training", "subjective_energy": 6},
])
def test_invalid_request_fields_are_rejected(values):
    with pytest.raises(ValidationError):
        CoachRequest.model_validate(values)


def test_invalid_dates_and_unknown_workouts_are_explicit(store):
    with pytest.raises(ValueError, match="past"):
        _context(store, next_session_date=date(2026, 10, 17))
    with pytest.raises(LookupError):
        _context(store, "workout_feedback", workout_id="missing")
    with pytest.raises(ValueError, match="future"):
        _context(store, "workout_feedback", workout_id="future")
    with pytest.raises(ValidationError):
        CoachingProfile(timezone="Not/AZone")


def test_preview_is_local_exportable_and_contains_no_key_or_raw_trackpoints(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-secret-never-export")
    response = client.post("/ai/coaching/preview", json={"purpose": "next_training"})
    assert response.status_code == 200
    preview = response.json()
    assert preview["api_configured"] is True
    assert INSTRUCTIONS in preview["copy_prompt"]
    assert "unit-test-secret-never-export" not in response.text
    assert "trackpoints" not in json.dumps(preview["context"])
    assert "source_file" not in json.dumps(preview["context"])
    assert len(preview["context_sha256"]) == 64
    assert client.get("/ai/coaching/history").json() == []
    assert client.get("/static/coaching.js").status_code == 200


def test_generation_requires_current_preview_and_configuration(client):
    request = {"purpose": "next_training"}
    assert client.post("/ai/coaching/generate", json=request).status_code == 409
    preview = client.post("/ai/coaching/preview", json=request).json()
    request["preview_hash"] = preview["context_sha256"]
    assert client.post("/ai/coaching/generate", json=request).status_code == 503
    assert client.put("/ai/coaching/profile", json={"goals": "Changed goal"}).status_code == 200
    assert client.post("/ai/coaching/generate", json=request).status_code == 409


def test_viewing_imported_workout_and_local_summary_never_calls_provider(client, monkeypatch):
    calls = _mock_provider(monkeypatch)
    assert client.get("/").status_code == 200
    assert client.get("/workouts").status_code == 200
    assert client.get("/workouts/latest/analysis").status_code == 200
    assert client.post("/ai/analyse-session", json={"workout_id": "latest"}).status_code == 200
    assert calls == []


@pytest.mark.parametrize("purpose", ["workout_feedback", "next_training"])
def test_api_response_is_saved_cached_and_provenance_is_complete(client, store, monkeypatch, purpose):
    calls = _mock_provider(monkeypatch, _output(purpose))
    request = {"purpose": purpose, **({"workout_id": "latest"} if purpose == "workout_feedback" else {})}
    preview = client.post("/ai/coaching/preview", json=request).json()
    request["preview_hash"] = preview["context_sha256"]
    first = client.post("/ai/coaching/generate", json=request)
    assert first.status_code == 200, first.text
    review = first.json()
    assert review["cached"] is False
    assert review["kind"] == purpose
    assert review["model"] == "gpt-5-mini-test"
    assert review["instructions"] == INSTRUCTIONS
    assert review["feature_snapshot_sha256"] == preview["context_sha256"]
    assert review["response_schema"] == CoachOutput.model_json_schema()
    assert review["usage"]["input_tokens"] == 100
    assert "unit-test-secret-never-export" not in first.text
    repeated = client.post("/ai/coaching/generate", json=request)
    assert repeated.status_code == 200
    assert repeated.json()["cached"] is True
    assert len(calls) == 1
    if purpose == "workout_feedback":
        saved_report = client.get("/workouts/latest/feedback").json()
        assert saved_report["available"] is True
    sent = json.loads(calls[0].content)
    assert sent["store"] is False
    assert sent["text"]["format"]["strict"] is True
    assert sent["max_output_tokens"] == 6000
    assert json.loads(sent["input"]) == preview["context"]
    history = client.get("/ai/coaching/history?workout_id=latest").json()
    assert len(history) == 1
    assert history[0]["id"] == review["id"]
    with SqliteStore(store.path) as reopened:
        assert reopened.get_coach_review(review["id"])["output"] == review["output"]
        reopened.delete_workout("latest")
        assert reopened.get_coach_review(review["id"]) is None
        assert reopened.get_workout_feedback("latest") is None


def test_saved_workout_report_informs_preparation_without_an_api_call(client, monkeypatch):
    calls = _mock_provider(monkeypatch)
    assert client.get("/workouts/latest/feedback").json() == {"available": False, "feedback": None}
    assert client.get("/workouts/missing/feedback").status_code == 404
    report = {"notes": "Harder than expected, especially the final ten minutes.", "perceived_exertion": 8}
    response = client.put("/workouts/latest/feedback", json=report)
    assert response.status_code == 200
    assert client.get("/workouts/latest/feedback").json()["feedback"] == report
    preview = client.post("/ai/coaching/preview", json={"purpose": "next_training"}).json()
    assert preview["context"]["selected_session"]["athlete_feedback"] == report
    recent = next(s for s in preview["context"]["recent_sessions"] if s["workout_id"] == "latest")
    assert recent["athlete_feedback"]["perceived_exertion"] == 8
    assert preview["context"]["current_recovery"] is None
    assert calls == []
    assert client.put("/workouts/latest/feedback", json={"perceived_exertion": 11}).status_code == 422


@pytest.mark.parametrize("status,expected", [(401,503), (403,503), (429,503), (500,502)])
def test_provider_http_failures_are_explicit_and_do_not_save(client, monkeypatch, status, expected):
    calls = _mock_provider(monkeypatch, status=status)
    request = {"purpose": "next_training"}
    request["preview_hash"] = client.post("/ai/coaching/preview", json=request).json()["context_sha256"]
    response = client.post("/ai/coaching/generate", json=request)
    assert response.status_code == expected
    assert "unit-test-secret-never-export" not in response.text
    assert len(calls) == 1
    assert client.get("/ai/coaching/history").json() == []


def test_provider_timeout_has_no_retry(client, monkeypatch):
    calls = _mock_provider(monkeypatch, timeout=True)
    request = {"purpose": "next_training"}
    request["preview_hash"] = client.post("/ai/coaching/preview", json=request).json()["context_sha256"]
    assert client.post("/ai/coaching/generate", json=request).status_code == 504
    assert len(calls) == 1


def test_advice_conflicting_with_local_pain_stop_is_never_saved(client, monkeypatch):
    calls = _mock_provider(monkeypatch, _output(action="easy"))
    request = {"purpose": "next_training", "concerning_pain": True}
    request["preview_hash"] = client.post("/ai/coaching/preview", json=request).json()["context_sha256"]
    response = client.post("/ai/coaching/generate", json=request)
    assert response.status_code == 502
    assert "safety" in response.json()["detail"]
    assert len(calls) == 1
    assert client.get("/ai/coaching/history").json() == []


def test_provider_must_supply_actual_model_and_response_provenance(store, monkeypatch):
    _mock_provider(monkeypatch, payload={
        "status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(_output())}
        ]}],
    })
    with pytest.raises(provider.CoachingError, match="validation"):
        provider.request_coaching(_context(store), "gpt-5-mini")


def test_current_day_advice_does_not_break_preview_cache_and_prior_advice_is_not_training(store):
    context = _context(store)
    review = {
        "id": "today", "kind": "next_training", "workout_id": "old",
        "generated_at": NOW.isoformat(), "output": _output(),
    }
    store.save_coach_review(review)
    assert context_hash(_context(store)) == context_hash(context)
    review.update(id="previous-day", generated_at=(NOW - timedelta(days=1)).isoformat())
    store.save_coach_review(review)
    context = _context(store)
    assert len(context["previous_coaching_unconfirmed"]) == 1
    assert context["history_coverage"]["recent_sessions_total"] == 2
    feedback = _context(store, "workout_feedback", workout_id="latest")
    assert feedback["previous_coaching_unconfirmed"] == []


@pytest.mark.parametrize("payload,expected", [
    ({"status": "incomplete", "output": []}, 502),
    ({"status": "completed", "output": [{"type": "message", "content": [
        {"type": "refusal", "refusal": "No"}]}]}, 422),
    ({"status": "completed", "output": []}, 502),
    ({"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": "not JSON"}]}]}, 502),
])
def test_incomplete_refused_and_invalid_output_is_not_saved(client, monkeypatch, payload, expected):
    _mock_provider(monkeypatch, payload=payload)
    request = {"purpose": "next_training"}
    request["preview_hash"] = client.post("/ai/coaching/preview", json=request).json()["context_sha256"]
    assert client.post("/ai/coaching/generate", json=request).status_code == expected
    assert client.get("/ai/coaching/history").json() == []


def test_safety_dates_duration_and_workflow_separation_are_enforced(store):
    context = _context(store, concerning_pain=True)
    with pytest.raises(ValueError, match="safety"):
        provider.validate_advice(CoachOutput.model_validate(_output()), context)
    context = _context(store, available_minutes=20)
    with pytest.raises(ValueError, match="available"):
        provider.validate_advice(CoachOutput.model_validate(_output()), context)
    output = _output()
    output["next_session"]["date"] = "2026-10-20"
    with pytest.raises(ValueError, match="date"):
        provider.validate_advice(CoachOutput.model_validate(output), context)
    feedback = _context(store, "workout_feedback", workout_id="latest")
    with pytest.raises(ValueError, match="feedback"):
        provider.validate_advice(CoachOutput.model_validate(_output()), feedback)
    invalid = _output()
    invalid["next_session"]["duration_min"] = 40
    with pytest.raises(ValidationError, match="add up"):
        CoachOutput.model_validate(invalid)
    invalid = _output()
    invalid["next_session"]["steps"][0]["duration_min"] = float("nan")
    with pytest.raises(ValidationError):
        CoachOutput.model_validate(invalid)

def _saved_review(index, kind="next_training", workout_id="latest"):
    return {
        "id": f"saved-{index}", "workout_id": workout_id, "kind": kind,
        "generated_at": (NOW + timedelta(minutes=index)).isoformat(),
        "model": "saved-test-model", "prompt_version": "coach-v1",
        "output": _output(kind), "feature_snapshot": {
            "safety": {"readiness": {"level": "amber", "recommendation": "Keep it easy."}},
        },
    }


def test_saved_training_is_filtered_before_limit_and_can_be_reopened(client, store, monkeypatch):
    calls = _mock_provider(monkeypatch)
    old_training = _saved_review(0)
    store.save_coach_review(old_training)
    for index in range(1, 16):
        store.save_coach_review(_saved_review(index, kind="workout_feedback"))
    assert all(review["kind"] == "workout_feedback"
               for review in client.get("/ai/coaching/history").json())
    assert client.get("/ai/coaching/history?kind=next_training").json() == [old_training]
    reopened = TestClient(create_app(store.path))
    assert reopened.get("/ai/coaching/history/saved-0").json() == old_training
    assert reopened.get("/ai/coaching/history/not-found").status_code == 404
    assert calls == []


def test_saved_history_filters_workout_and_paginates_on_the_server(client, store):
    for index in range(16):
        store.save_coach_review(_saved_review(
            index, kind="workout_feedback" if index % 2 else "next_training",
            workout_id="old" if index < 8 else "latest",
        ))
    response = client.get(
        "/ai/coaching/history?kind=next_training&workout_id=latest&limit=2&offset=1"
    )
    assert response.status_code == 200
    assert [review["id"] for review in response.json()] == ["saved-12", "saved-10"]
    assert len(client.get("/ai/coaching/history?kind=next_training&limit=50").json()) == 8
    for query in ("kind=other", "limit=0", "limit=51", "offset=-1"):
        assert client.get("/ai/coaching/history?" + query).status_code == 422


def test_default_morning_window_caps_total_time_without_assuming_thirty_minutes(store):
    context = _context(store)
    window = context["training_window"]
    assert window["start_local"] == "06:00"
    assert window["finish_by_local"] == "07:00"
    assert window["available_minutes"] == 60
    assert window["maximum_total_minutes"] == 60
    assert window["includes_warmup_recoveries_cooldown"] is True
    assert "Do not assume a 30-minute run" in INSTRUCTIONS
    for duration in (20, 45, 60):
        provider.validate_advice(CoachOutput.model_validate(_output(duration=duration)), context)
    with pytest.raises(ValueError, match="available training time"):
        provider.validate_advice(CoachOutput.model_validate(_output(duration=60.1)), context)
    rounding_overrun = _output(duration=60)
    rounding_overrun["next_session"]["steps"][0]["duration_min"] = 60.05
    with pytest.raises(ValueError, match="available training time"):
        provider.validate_advice(CoachOutput.model_validate(rounding_overrun), context)
    assert _context(store, available_minutes=360)["training_window"]["available_minutes"] == 60
    assert _context(store, available_minutes=40)["training_window"]["available_minutes"] == 40


def test_shorter_profile_window_and_request_limits_are_respected(client, store):
    response = client.put("/ai/coaching/profile", json={
        "usual_training_start": "06:15", "usual_training_end": "07:00",
        "max_session_minutes": 60, "goals": "Preserved goal",
    })
    assert response.status_code == 200
    profile = client.get("/ai/coaching/profile").json()
    assert profile["usual_training_start"] == "06:15"
    assert profile["goals"] == "Preserved goal"
    assert _context(store)["training_window"]["available_minutes"] == 45
    assert _context(store, available_minutes=35)["training_window"]["available_minutes"] == 35
    assert client.put("/ai/coaching/profile", json={"max_session_minutes": 30}).status_code == 200
    assert _context(store)["training_window"]["available_minutes"] == 30
    assert _context(store, "workout_feedback", workout_id="latest")["training_window"] is None
    for invalid in (
        {"usual_training_start": "07:00", "usual_training_end": "06:00"},
        {"usual_training_start": "25:00"}, {"max_session_minutes": 61},
        {"usual_training_start": "06:59", "usual_training_end": "07:00"},
    ):
        assert client.put("/ai/coaching/profile", json=invalid).status_code == 422


def test_races_can_be_edited_cancelled_and_removed(client):
    payload = {"name": "July 5k", "race_date": "2027-07-04",
               "distance_m": 5000, "priority": "A", "verified": True}
    response = client.post("/races", json=payload)
    assert response.status_code == 200
    rid = response.json()["id"]
    race = client.get("/races").json()[0]
    assert race["priority"] == "A"
    assert race["race_date"] == "2027-07-04"
    payload["status"] = "cancelled"
    assert client.put(f"/races/{rid}", json=payload).status_code == 200
    preview = client.post("/ai/coaching/preview", json={"purpose": "next_training"}).json()
    assert preview["context"]["races"] == []
    assert client.delete(f"/races/{rid}").status_code == 200
    assert client.delete(f"/races/{rid}").status_code == 404
    assert client.post("/races", json={"name": "Bad", "race_date": "July"}).status_code == 422
    assert client.post("/races", json={"name": " ", "distance_m": -1}).status_code == 422


def test_legacy_race_schema_migrates_idempotently(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE races (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        race_date TEXT, distance_m REAL, target_time_s INTEGER, verified INTEGER DEFAULT 0);
        INSERT INTO races (name, race_date) VALUES ('Existing race', '2027-07-04');
    """)
    conn.close()
    for _ in range(2):
        with SqliteStore(path) as store:
            race = store.list_races()[0]
            assert race["priority"] == "B"
            assert race["status"] == "planned"
            assert race["notes"] == ""
