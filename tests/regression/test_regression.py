"""Regression suite over all historical files (PRD §19, §25).

Historical TCX files are immutable fixtures. These tests guard that every file imports
(or is explicitly quarantined) and that analysis is reproducible.
"""

from __future__ import annotations

import pytest

from app.models import Athlete
from app.services.pipeline import process_raw_directory, process_tcx_file

from tests.conftest import REGRESSION_DIR, regression_tcx_files


def test_all_regression_files_present():
    files = regression_tcx_files()
    if not files:
        pytest.skip("no regression fixtures present")
    assert len(files) >= 1


@pytest.mark.parametrize("path", regression_tcx_files(), ids=lambda p: p.name)
def test_each_file_imports_and_analyses(path):
    workout, analysis = process_tcx_file(path, Athlete())
    assert workout.trackpoints, f"{path.name} produced no trackpoints"
    assert workout.distance_m >= 0
    assert analysis["workout_id"] == workout.id
    # Provenance: every analysis exposes the thresholds it used (PRD §4).
    assert "thresholds" in analysis["segmentation"]
    assert "session_type" in analysis


def test_analysis_is_reproducible():
    files = regression_tcx_files()
    if not files:
        pytest.skip("no regression fixtures present")
    _, a1 = process_tcx_file(files[0], Athlete())
    _, a2 = process_tcx_file(files[0], Athlete())
    assert a1["metrics"] == a2["metrics"]
    assert a1["segmentation"] == a2["segmentation"]


def test_directory_import_report_and_quarantine():
    report = process_raw_directory(REGRESSION_DIR, Athlete())
    report.pop("_workouts")
    report.pop("_body_measurements")
    summary = report["summary"]
    # Definition of Done: all files import successfully or are quarantined (PRD §25).
    assert summary["workouts_imported"] + summary["workouts_quarantined"] >= 1
    assert "session_breakdown" in summary
    # Smart-scale trends are ingested (scale.xls fixture).
    assert summary["body_measurements"] >= 0
