"""Synthetic edge-case tests (PRD §19): missing HR, spikes, flatlines, GPS jumps, etc."""

from __future__ import annotations

from app.analytics.quality import annotate_hr_quality
from app.models.enums import QualityFlag

from tests.conftest import make_workout


def _flags(workout):
    flags = set()
    for p in workout.trackpoints:
        flags.update(p.quality)
    return flags


def test_missing_hr_flagged():
    w = make_workout([{"t": i, "speed": 2.5, "hr": None} for i in range(20)])
    annotate_hr_quality(w)
    assert QualityFlag.HR_MISSING in _flags(w)


def test_hr_spike_flagged_as_implausible_jump():
    samples = [{"t": i, "speed": 2.5, "hr": 140} for i in range(10)]
    samples[5]["hr"] = 200  # sudden +60 bpm spike in 1 second
    w = make_workout(samples)
    annotate_hr_quality(w)
    assert QualityFlag.HR_IMPLAUSIBLE_JUMP in _flags(w)


def test_hr_flatline_flagged():
    w = make_workout([{"t": i, "speed": 2.5, "hr": 150} for i in range(40)])
    annotate_hr_quality(w)
    assert QualityFlag.HR_FLATLINE in _flags(w)


def test_pause_and_resume_handled_in_metrics():
    from app.analytics.metrics import basic_metrics

    samples = (
        [{"t": i, "speed": 2.5, "hr": 140} for i in range(30)]
        + [{"t": 30 + i, "speed": 0.0, "hr": 120} for i in range(20)]  # pause
        + [{"t": 50 + i, "speed": 2.5, "hr": 140} for i in range(30)]  # resume
    )
    w = make_workout(samples)
    m = basic_metrics(w)
    assert m["paused_s"] > 0
    assert m["moving_s"] > 0


def test_termination_only_one_point():
    # A recording that ends almost immediately should not crash analytics.
    from app.analytics.metrics import basic_metrics

    w = make_workout([{"t": 0, "speed": 0.0, "hr": 90}])
    m = basic_metrics(w)
    assert m["duration_s"] == 0.0
