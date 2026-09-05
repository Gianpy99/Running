"""Shared pytest fixtures (PRD §19)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Trackpoint, Workout  # noqa: E402

REGRESSION_DIR = ROOT / "data" / "regression"


def regression_tcx_files() -> list[Path]:
    return sorted(REGRESSION_DIR.glob("*.tcx"))


@pytest.fixture
def regression_files() -> list[Path]:
    return regression_tcx_files()


def make_workout(samples: list[dict], start: datetime | None = None) -> Workout:
    """Build a synthetic workout from a list of {t, speed, hr, alt, dist} dicts."""
    start = start or datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc)
    pts: list[Trackpoint] = []
    cum = 0.0
    for i, s in enumerate(samples):
        ts = start + timedelta(seconds=s.get("t", i))
        speed = s.get("speed")
        if "dist" in s:
            cum = s["dist"]
        elif speed is not None and i > 0:
            dt = (ts - pts[-1].timestamp).total_seconds()
            cum += speed * dt
        pts.append(
            Trackpoint(
                timestamp=ts,
                elapsed_s=(ts - start).total_seconds(),
                distance_m=cum,
                speed_mps=speed,
                hr_bpm=s.get("hr"),
                altitude_m=s.get("alt"),
                latitude=s.get("lat"),
                longitude=s.get("lon"),
            )
        )
    return Workout(
        id="synthetic",
        start_time=start,
        duration_s=pts[-1].elapsed_s if pts else 0.0,
        distance_m=cum,
        trackpoints=pts,
    )
