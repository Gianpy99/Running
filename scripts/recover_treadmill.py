"""Restore treadmill sessions from their original TCX files after a bad edit.

An edit that regenerated a treadmill session replaced its measured trackpoints with
synthetic ones, losing the real heart rate. This re-imports the authoritative TCX files
and, if a synthetic manually-logged session exists for the same day, carries over its
phase-description notes and removes the stale row.

Usage:
    python scripts/recover_treadmill.py <file1.tcx> [file2.tcx ...]

The target database is resolved exactly like the app: DATABASE_URL, then COACH_DB, then
data/coach.db. Set DATABASE_URL to recover the deployed (Postgres) database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.analytics.analysis import analyse_workout
from app.analytics.terrain import infer_terrain
from app.ingestion import parse_tcx_file
from app.models import Athlete
from app.persistence import open_store
from app.services.classification import classify_session


def recover(paths: list[str], dsn: str | None = None) -> None:
    dsn = dsn or os.environ.get("DATABASE_URL") or os.environ.get("COACH_DB", "data/coach.db")
    print(f"database: {dsn.split('@')[-1] if '@' in dsn else dsn}")
    athlete = Athlete()
    with open_store(dsn) as store:
        existing = store.list_workouts()
        for path in paths:
            workout = parse_tcx_file(path)
            day = workout.start_time.date().isoformat()

            # Carry the phase description over from a synthetic same-day session, then drop it.
            for row in existing:
                if row["start_time"][:10] != day or row["id"] == workout.id:
                    continue
                prior = store.get_workout(row["id"])
                if prior is not None and prior.source == "manual_treadmill":
                    if prior.notes:
                        workout.notes = prior.notes
                    store.delete_workout(row["id"])
                    print(f"  removed synthetic {row['id']} (kept its notes)")

            workout.terrain = infer_terrain(workout)
            workout.session_type = classify_session(workout)
            analysis = analyse_workout(workout, athlete)
            store.upsert_workout(workout, analysis)
            km = round((workout.distance_m or 0) / 1000.0, 2)
            print(f"restored {workout.id} from {Path(path).name}: "
                  f"avg_hr={workout.avg_hr}, {km} km, terrain={workout.terrain.value}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/recover_treadmill.py <file1.tcx> [file2.tcx ...]")
        raise SystemExit(2)
    recover(sys.argv[1:])
