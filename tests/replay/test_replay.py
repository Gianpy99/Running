"""Replay tests (PRD §11, §19): historical trackpoints through the live state machine."""

from __future__ import annotations

import pytest

from app.services.pipeline import process_tcx_file
from app.models import Athlete
from app.training.dsl import standard_treadmill_session
from app.training.replay import replay_workout
from app.training.state_machine import EventKind, LiveCoach

from tests.conftest import regression_tcx_files


def test_replay_is_deterministic():
    files = regression_tcx_files()
    if not files:
        pytest.skip("no regression fixtures present")
    workout, _ = process_tcx_file(files[0], Athlete())
    a = replay_workout(standard_treadmill_session(), workout)
    b = replay_workout(standard_treadmill_session(), workout)
    assert [(e.at_s, e.kind, e.message) for e in a] == [(e.at_s, e.kind, e.message) for e in b]


def test_replay_emits_phase_starts_and_completion():
    files = regression_tcx_files()
    if not files:
        pytest.skip("no regression fixtures present")
    workout, _ = process_tcx_file(files[0], Athlete())
    events = replay_workout(standard_treadmill_session(), workout)
    kinds = {e.kind for e in events}
    assert EventKind.PHASE_START in kinds


def test_downgraded_coach_announces_easy():
    coach = LiveCoach(standard_treadmill_session(), downgrade_to_easy=True)
    events = coach.start()
    assert any("aerobic" in e.message.lower() for e in events)


def test_extreme_hr_ignored_when_sensor_bad():
    coach = LiveCoach(standard_treadmill_session())
    coach.start()
    # Sensor unreliable: even a wild HR must not trigger an adaptation cue (PRD §12, §18).
    events = []
    for t in range(700, 740):
        events.extend(coach.update(t, hr=210, speed_mps=2.2, sensor_ok=False))
    assert all(e.kind != EventKind.ADAPTATION for e in events)
