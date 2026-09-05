"""Unit tests: readiness rules and deterministic downgrade (PRD §10, §26)."""

from __future__ import annotations

from datetime import date

from app.models import Athlete, RecoveryContext
from app.models.enums import ReadinessLevel
from app.services.readiness import compute_readiness
from app.training.dsl import standard_treadmill_session
from app.training.planner import adapt_definition


def test_readiness_green_when_no_limiting_context():
    r = compute_readiness(None, Athlete())
    assert r.level == ReadinessLevel.GREEN
    assert r.score >= 75


def test_readiness_concerning_pain_forces_red_stop():
    ctx = RecoveryContext(for_date=date.today(), concerning_pain=True)
    r = compute_readiness(ctx, Athlete())
    assert r.level == ReadinessLevel.RED
    assert r.stop_workout is True


def test_readiness_poor_sleep_heavy_legs_downgrades(guiding_example_context):
    """PRD §26 guiding example: poor sleep + heavy legs => not green."""
    r = compute_readiness(guiding_example_context, Athlete())
    assert r.level in (ReadinessLevel.AMBER, ReadinessLevel.RED)
    assert any("sleep" in reason.lower() for reason in r.reasons)


def test_amber_reduces_intensity_phase_duration():
    from app.services.readiness import ReadinessResult

    amber = ReadinessResult(level=ReadinessLevel.AMBER, score=60)
    base = standard_treadmill_session()
    adapted = adapt_definition(base, amber)
    base_prog = next(p for p in base.phases if p.type.value == "progression")
    adapted_prog = next(p for p in adapted.phases if p.type.value == "progression")
    assert adapted_prog.duration_min < base_prog.duration_min


def test_red_downgrades_to_easy_aerobic():
    from app.services.readiness import ReadinessResult

    red = ReadinessResult(level=ReadinessLevel.RED, score=30)
    adapted = adapt_definition(standard_treadmill_session(), red)
    assert "downgraded" in adapted.name
    assert all(p.type.value in ("warmup", "aerobic", "cooldown") for p in adapted.phases)


import pytest


@pytest.fixture
def guiding_example_context() -> RecoveryContext:
    return RecoveryContext(for_date=date.today(), sleep_hours=4.5, leg_fatigue=4,
                           subjective_energy=2)
