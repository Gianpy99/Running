"""Persistence backend tests (PRD §6).

Covers the dual-backend store: SQLite (always) and PostgreSQL (opt-in).

The PostgreSQL integration test only runs when a reachable DSN is provided via the
``RUNNING_COACH_TEST_DATABASE_URL`` environment variable (e.g. in CI or on the Pi
against the shared PostgreSQL). It is skipped otherwise so the suite stays hermetic.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest

from app.models import BodyMeasurement, RecoveryContext, Workout
from app.persistence import PostgresStore, SqliteStore, open_store
from app.persistence.store import _BaseStore


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
