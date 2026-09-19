"""Persistence backend tests (PRD §6).

Covers the dual-backend store: SQLite (always) and PostgreSQL (opt-in).

The PostgreSQL integration test only runs when a reachable DSN is provided via the
``RUNNING_COACH_TEST_DATABASE_URL`` environment variable (e.g. in CI or on the Pi
against the shared PostgreSQL). It is skipped otherwise so the suite stays hermetic.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import date, datetime, timezone

import pytest

from app.models import BodyMeasurement, RecoveryContext, Workout
from app.persistence import PostgresStore, SqliteStore, open_store
from app.persistence.store import _BaseStore


_LEGACY_SCHEMA = """
CREATE TABLE workouts (
    id TEXT PRIMARY KEY, source TEXT, source_file TEXT, start_time TEXT NOT NULL,
    duration_s REAL, distance_m REAL, session_type TEXT, terrain TEXT, completion TEXT,
    avg_hr INTEGER, avg_pace_s_per_km REAL, elevation_gain_m REAL, notes TEXT,
    canonical_json TEXT NOT NULL
);
CREATE TABLE analyses (workout_id TEXT PRIMARY KEY, analysis_json TEXT NOT NULL);
"""


def _legacy_database(path: str, workout: Workout) -> None:
    """Write a database shaped like the schema that shipped before main-set metrics."""
    conn = sqlite3.connect(path)
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute(
        """INSERT INTO workouts (id, source, start_time, duration_s, distance_m, session_type,
           terrain, completion, avg_hr, avg_pace_s_per_km, notes, canonical_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (workout.id, workout.source, workout.start_time.isoformat(), workout.duration_s,
         workout.distance_m, "easy", "treadmill", "unknown", 145, 511.0,
         workout.notes, workout.model_dump_json()),
    )
    conn.execute(
        "INSERT INTO analyses VALUES (?, ?)",
        (workout.id, json.dumps({"metrics": {"avg_pace_s_per_km": 511.0}})),
    )
    conn.commit()
    conn.close()


def test_opening_a_legacy_database_adds_the_new_columns(tmp_path):
    """A deployed database predates the main-set columns; opening it must migrate, not fail."""
    from app.ingestion import build_treadmill_workout

    db = str(tmp_path / "legacy.db")
    workout = build_treadmill_workout("10 min warmup at 4mph\n25 min at 4.7mph\n5 min cooldown")
    _legacy_database(db, workout)

    with open_store(db) as store:
        row = store.list_workouts()[0]
        assert row["main_set_avg_pace_s_per_km"] is None  # column exists, not yet populated
        # Re-opening must stay a no-op rather than re-adding the column.
    with open_store(db) as store:
        assert "main_set_avg_hr" in store.list_workouts()[0]


def test_reanalyse_backfills_main_set_metrics_for_stored_workouts(tmp_path):
    """Sessions imported by an older build get the new metrics without a re-import (§27)."""
    from app.ingestion import build_treadmill_workout
    from app.services.pipeline import reanalyse_stored_workouts

    db = str(tmp_path / "legacy.db")
    workout = build_treadmill_workout("10 min warmup at 4mph\n25 min at 4.7mph\n5 min cooldown")
    _legacy_database(db, workout)

    with open_store(db) as store:
        assert reanalyse_stored_workouts(store) == 1
        row = store.list_workouts()[0]
        # Warmup/cooldown excluded, so the main set is faster than the stored session pace.
        assert row["main_set_avg_pace_s_per_km"] < row["avg_pace_s_per_km"]
        assert store.get_analysis(workout.id)["metrics_main_set"]["method"] == "declared"
        # Already-current workouts are skipped on the next pass.
        assert reanalyse_stored_workouts(store) == 0


def test_reanalyse_rebuilds_analyses_written_by_a_superseded_version(tmp_path):
    """An older build can leave the right keys holding stale values, so check the version.

    Presence of `metrics_main_set` is not evidence it is current: the first release of the
    feature wrote that key with figures a later build supersedes.
    """
    from app.analytics.analysis import ANALYSIS_VERSION
    from app.ingestion import build_treadmill_workout
    from app.services.pipeline import reanalyse_stored_workouts

    db = str(tmp_path / "stale.db")
    workout = build_treadmill_workout("10 min warmup at 4mph\n25 min at 4.7mph\n5 min cooldown")
    _legacy_database(db, workout)

    with open_store(db) as store:
        store._exec(
            "UPDATE analyses SET analysis_json = ? WHERE workout_id = ?",
            (json.dumps({"analysis_version": ANALYSIS_VERSION - 1,
                         "metrics_main_set": {"available": True, "avg_pace_s_per_km": 1.0}}),
             workout.id),
        )
        store.conn.commit()
        assert reanalyse_stored_workouts(store) == 1
        analysis = store.get_analysis(workout.id)
        assert analysis["analysis_version"] == ANALYSIS_VERSION
        assert analysis["metrics_main_set"]["avg_pace_s_per_km"] > 1.0


def test_open_store_selects_sqlite_for_paths(tmp_path):
    store = open_store(str(tmp_path / "x.db"))
    assert isinstance(store, SqliteStore)
    store.close()


def test_open_store_detects_postgres_scheme(monkeypatch):
    # Route to PostgresStore without a real connection: assert the scheme is detected
    # by intercepting the constructor.
    captured = {}

    def fake_init(self, dsn):
        captured["dsn"] = dsn

    monkeypatch.setattr(PostgresStore, "__init__", fake_init)
    store = open_store("postgresql://user:pw@host:1433/db")
    assert isinstance(store, PostgresStore)
    assert captured["dsn"] == "postgresql://user:pw@host:1433/db"


def test_placeholder_translation():
    sqlite_store = _BaseStore()
    sqlite_store.ph = "?"
    assert sqlite_store._q("a=? AND b=?") == "a=? AND b=?"

    pg_store = _BaseStore()
    pg_store.ph = "%s"
    assert pg_store._q("a=? AND b=?") == "a=%s AND b=%s"


def _sample_workout(wid: str) -> Workout:
    start = datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc)
    return Workout(id=wid, start_time=start, duration_s=1800.0, distance_m=5000.0)


def _roundtrip(store: _BaseStore) -> None:
    wid = f"test-{uuid.uuid4().hex[:8]}"
    workout = _sample_workout(wid)
    try:
        store.upsert_workout(workout, {"metrics": {"distance_km": 5.0}})
        assert any(w["id"] == wid for w in store.list_workouts())
        assert store.get_workout(wid).id == wid
        assert store.get_analysis(wid)["metrics"]["distance_km"] == 5.0

        store.upsert_body_measurements(
            [BodyMeasurement(timestamp=datetime(2026, 1, 1, 6, 0), weight_kg=80.0)]
        )
        assert any(m.weight_kg == 80.0 for m in store.list_body_measurements())

        ctx = RecoveryContext(for_date=date(2026, 1, 1), sleep_hours=6.0)
        store.upsert_recovery(ctx)
        assert store.get_recovery(date(2026, 1, 1)).sleep_hours == 6.0

        race_id = store.add_race("Test 5k", "2026-06-01", 5000.0, 1500, True)
        assert isinstance(race_id, int)
        assert any(r["id"] == race_id for r in store.list_races())
    finally:
        # Clean up rows this test created (important for a shared PostgreSQL).
        store._exec("DELETE FROM analyses WHERE workout_id = ?", (wid,))
        store._exec("DELETE FROM workouts WHERE id = ?", (wid,))
        store._exec("DELETE FROM body_measurements WHERE timestamp = ?",
                    (datetime(2026, 1, 1, 6, 0).isoformat(),))
        store._exec("DELETE FROM recovery_context WHERE for_date = ?", ("2026-01-01",))
        store._exec("DELETE FROM races WHERE name = ?", ("Test 5k",))
        store.conn.commit()


def test_sqlite_roundtrip(tmp_path):
    with SqliteStore(tmp_path / "rt.db") as store:
        _roundtrip(store)


@pytest.mark.skipif(
    not (os.environ.get("RUNNING_COACH_TEST_DATABASE_URL", "").startswith(
        ("postgres://", "postgresql://"))),
    reason="Set RUNNING_COACH_TEST_DATABASE_URL to a PostgreSQL DSN to run this test.",
)
def test_postgres_roundtrip():
    dsn = os.environ["RUNNING_COACH_TEST_DATABASE_URL"]
    with open_store(dsn) as store:
        assert isinstance(store, PostgresStore)
        _roundtrip(store)
