"""Unit tests: analytics — metrics, segmentation, terrain, efficiency, drift, load."""

from __future__ import annotations

from app.analytics.analysis import analyse_workout
from app.analytics.efficiency import aerobic_efficiency, hr_drift
from app.analytics.load import training_load
from app.analytics.mainset import main_set_metrics, main_set_window
from app.analytics.metrics import basic_metrics
from app.analytics.segmentation import segment_workout
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


def _outdoor_tempo_run():
    """10 min easy, 30 min tempo, 5 min easy — with GPS, so it is not a treadmill run."""
    speeds = [2.0] * 120 + [2.9] * 360 + [2.0] * 60
    return make_workout([
        {"t": i * 5, "speed": s, "hr": 130 if s < 2.5 else 160, "lat": 51.0 + i * 1e-5, "lon": -0.5}
        for i, s in enumerate(speeds)
    ])


def test_outdoor_runs_keep_their_calculated_figures():
    """Trimming outdoor runs by pace only ever tracked GPS noise, so it is not attempted."""
    window = main_set_window(_outdoor_tempo_run())
    assert window["available"] is False
    assert window["reason"] == "not_treadmill"


def test_treadmill_run_uses_the_athletes_habitual_structure():
    """No description, so the athlete's usual 10 min warmup / 5 min cooldown is applied."""
    w = make_workout(_steady_run(3000, 2.5, 150))  # no GPS -> treadmill
    window = main_set_window(w, Athlete())
    assert window["available"] is True
    assert window["method"] == "athlete_default"
    assert window["start_s"] == 600.0
    assert window["end_s"] == w.duration_s - 300.0  # the 5 min cooldown, off the end


def test_athlete_with_no_habitual_structure_gets_no_main_set():
    athlete = Athlete(treadmill_warmup=[], treadmill_cooldown=[])
    w = make_workout(_steady_run(3000, 2.5, 150))
    assert main_set_window(w, athlete)["available"] is False


def test_main_set_metrics_isolate_the_real_effort():
    """A treadmill session whose easy ends are slower than the work in the middle."""
    samples = (
        [{"t": t, "speed": 1.8, "hr": 120} for t in range(0, 600, 5)]
        + [{"t": t, "speed": 2.9, "hr": 160} for t in range(600, 2700, 5)]
        + [{"t": t, "speed": 1.8, "hr": 125} for t in range(2700, 3000, 5)]
    )
    w = make_workout(samples)
    whole, main = basic_metrics(w), main_set_metrics(w, Athlete())
    assert main["pace_source"] == "recorded"
    assert main["avg_pace_s_per_km"] < whole["avg_pace_s_per_km"]
    assert main["avg_hr"] == 160  # the work only, none of the easy running
    assert main["duration_s"] == w.duration_s - 900.0


def test_analyse_workout_exposes_main_set_metrics():
    w = make_workout(_steady_run(3000, 2.5, 150))
    result = analyse_workout(w, Athlete(max_hr=185))
    ms = result["metrics_main_set"]
    assert ms["available"] is True
    # The workout carries the figures so trend charts need no per-session analysis fetch.
    assert w.main_set_avg_pace_s_per_km == ms["avg_pace_s_per_km"]
    assert w.main_set_avg_hr == ms["avg_hr"]
