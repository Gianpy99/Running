"""Unit tests: analytics — metrics, segmentation, terrain, efficiency, drift, load."""

from __future__ import annotations

from app.analytics.analysis import analyse_workout
from app.analytics.efficiency import aerobic_efficiency, hr_drift
from app.analytics.load import training_load
from app.analytics.metrics import basic_metrics
from app.analytics.segmentation import main_set_window, segment_workout
from app.analytics.terrain import elevation_profile, equivalent_flat_pace
from app.models import Athlete

from tests.conftest import make_workout


def _steady_run(seconds: int, speed: float, hr: int, alt_step: float = 0.0):
    return [
        {"t": i, "speed": speed, "hr": hr, "alt": 10.0 + alt_step * i}
        for i in range(seconds)
    ]


def test_basic_metrics_moving_and_walking():
    samples = _steady_run(60, 2.5, 140) + [{"t": 60 + i, "speed": 1.0, "hr": 120} for i in range(30)]
    w = make_workout(samples)
    m = basic_metrics(w)
    assert m["moving_s"] > 0
    assert m["walking_s"] > 0  # the 1.0 m/s tail counts as walking
    assert m["avg_hr"] is not None


def test_segmentation_detects_walking_and_running():
    samples = _steady_run(120, 2.6, 140) + [{"t": 120 + i, "speed": 1.0, "hr": 120} for i in range(60)]
    seg = segment_workout(w := make_workout(samples))
    types = {s["type"] for s in seg["segments"]}
    assert "steady_aerobic" in types
    assert "walking" in types
    assert "thresholds" in seg


def test_equivalent_flat_pace_treadmill_unavailable():
    # No GPS/lat-lon -> treadmill -> equivalent-flat pace unavailable (PRD §9.4).
    w = make_workout(_steady_run(60, 2.5, 140))
    res = equivalent_flat_pace(w)
    assert res["available"] is False
    assert res["reason"] == "treadmill_no_gps"


def test_equivalent_flat_pace_hilly_available():
    samples = [
        {"t": i, "speed": 2.5, "hr": 150, "alt": 10 + 0.1 * i,
         "lat": 51.0 + i * 1e-5, "lon": -0.5, "dist": 2.5 * i}
        for i in range(600)
    ]
    w = make_workout(samples)
    res = equivalent_flat_pace(w)
    assert res["available"] is True
    assert res["equivalent_flat_pace_s_per_km"] > 0
    assert 0 < res["confidence"] <= 1.0


def test_aerobic_efficiency_available_for_steady():
    w = make_workout(_steady_run(700, 2.5, 145))
    eff = aerobic_efficiency(w)
    assert eff["available"] is True
    assert eff["efficiency_mps_per_bpm"] > 0


def test_hr_drift_unavailable_for_short():
    w = make_workout(_steady_run(120, 2.5, 145))
    assert hr_drift(w)["available"] is False


def test_training_load_hr_weighted():
    w = make_workout(_steady_run(600, 2.5, 150))
    tl = training_load(w, Athlete(max_hr=185))
    assert tl["method"] == "hr_weighted"
    assert tl["load"] > 0
    assert tl["counts_toward_planned_load"] is True


def test_elevation_profile_gain():
    w = make_workout([{"t": i, "speed": 2.5, "hr": 140, "alt": 10 + i, "dist": 2.5 * i} for i in range(20)])
    prof = elevation_profile(w)
    assert prof["has_elevation"] is True
    assert prof["elevation_gain_m"] > 0


def _treadmill_like_run():
    """10 min slow warmup, 35 min main set at a faster steady pace, 5 min slow cooldown."""
    samples = (
        [{"t": t, "speed": 2.0, "hr": 120} for t in range(0, 600, 5)]
        + [{"t": t, "speed": 2.6, "hr": 155} for t in range(600, 2700, 5)]
        + [{"t": t, "speed": 2.0, "hr": 125} for t in range(2700, 3000, 5)]
    )
    return make_workout(samples)


def test_main_set_window_trims_warmup_and_cooldown():
    w = _treadmill_like_run()
    window = main_set_window(w)
    assert window is not None
    start_s, end_s = window
    assert 590 <= start_s <= 610
    assert 2690 <= end_s <= 2710


def test_main_set_metrics_pace_faster_than_whole_session():
    w = _treadmill_like_run()
    whole = basic_metrics(w)
    window = main_set_window(w)
    main = basic_metrics(w, window=window)
    # Warmup/cooldown were slower, so trimming them should yield a faster (lower) pace.
    assert main["avg_pace_s_per_km"] < whole["avg_pace_s_per_km"]
    assert main["avg_hr"] > whole["avg_hr"]


def test_analyse_workout_exposes_metrics_main_set():
    w = _treadmill_like_run()
    result = analyse_workout(w, Athlete(max_hr=185))
    ms = result["metrics_main_set"]
    assert ms["available"] is True
    assert ms["trimmed_s"] > 0
    assert ms["avg_pace_s_per_km"] < result["metrics"]["avg_pace_s_per_km"]


def test_main_set_unavailable_when_no_warmup_cooldown():
    w = make_workout(_steady_run(600, 2.5, 150))
    result = analyse_workout(w, Athlete(max_hr=185))
    assert result["metrics_main_set"]["available"] is False
