"""Persistence layer (PRD §6 — "SQLite initially; PostgreSQL migration path").

Two interchangeable backends share one repository interface:

* :class:`SqliteStore` — local-first, file-based (default; used by tests and the CLI).
* :class:`PostgresStore` — shared PostgreSQL (production / Raspberry Pi family portal).

The backend is chosen by :func:`open_store` from a DSN/path: a ``postgres://`` or
``postgresql://`` URL selects PostgreSQL, anything else is treated as a SQLite path.
Raw source files remain authoritative (PRD §27); the store keeps canonical workout
summaries plus their full JSON, analyses, body measurements, recovery context and races.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from ..models import BodyMeasurement, RecoveryContext, Workout

# --- Schema (portable across SQLite and PostgreSQL) --------------------------
# Timestamps are stored as ISO-8601 TEXT to keep the canonical model byte-for-byte
# reproducible on both backends. ``ON CONFLICT ... DO UPDATE`` (upsert) and the
# ``excluded`` pseudo-table are supported by both SQLite (>=3.24) and PostgreSQL.

_COMMON_TABLES = """
CREATE TABLE IF NOT EXISTS workouts (
    id TEXT PRIMARY KEY,
    source TEXT,
    source_file TEXT,
    start_time TEXT NOT NULL,
    duration_s {REAL},
    distance_m {REAL},
    session_type TEXT,
    terrain TEXT,
    completion TEXT,
    avg_hr INTEGER,
    avg_pace_s_per_km {REAL},
    elevation_gain_m {REAL},
    notes TEXT,
    canonical_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    workout_id TEXT PRIMARY KEY REFERENCES workouts(id) ON DELETE CASCADE,
    analysis_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS body_measurements (
    timestamp TEXT PRIMARY KEY,
    weight_kg {REAL} NOT NULL,
    body_fat_pct {REAL},
    muscle_mass_kg {REAL},
    water_pct {REAL},
    source TEXT
);
CREATE TABLE IF NOT EXISTS recovery_context (
    for_date TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL
);
"""

_RACES_SQLITE = """
CREATE TABLE IF NOT EXISTS races (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    race_date TEXT,
    distance_m REAL,
    target_time_s INTEGER,
    verified INTEGER DEFAULT 0
);
"""

_RACES_POSTGRES = """
CREATE TABLE IF NOT EXISTS races (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    race_date TEXT,
    distance_m DOUBLE PRECISION,
    target_time_s INTEGER,
    verified BOOLEAN DEFAULT FALSE
);
"""


class _BaseStore:
    """Shared repository logic. Subclasses supply the connection + dialect.

    Query strings are written with ``?`` placeholders and translated to the
    backend's paramstyle by :meth:`_q`.
    """

    ph: str = "?"  # parameter placeholder for this backend

    def _q(self, sql: str) -> str:
        return sql if self.ph == "?" else sql.replace("?", self.ph)

    def _exec(self, sql: str, params: tuple = ()):
        return self.conn.execute(self._q(sql), params)

    def __enter__(self) -> "_BaseStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # --- workouts ---
    def upsert_workout(self, workout: Workout, analysis: dict | None = None) -> None:
        self._exec(
            """INSERT INTO workouts
               (id, source, source_file, start_time, duration_s, distance_m,
                session_type, terrain, completion, avg_hr, avg_pace_s_per_km,
                elevation_gain_m, notes, canonical_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 source=excluded.source, source_file=excluded.source_file,
                 start_time=excluded.start_time, duration_s=excluded.duration_s,
                 distance_m=excluded.distance_m, session_type=excluded.session_type,
                 terrain=excluded.terrain, completion=excluded.completion,
                 avg_hr=excluded.avg_hr, avg_pace_s_per_km=excluded.avg_pace_s_per_km,
                 elevation_gain_m=excluded.elevation_gain_m, notes=excluded.notes,
                 canonical_json=excluded.canonical_json""",
            (
                workout.id, workout.source, workout.source_file,
                workout.start_time.isoformat(), workout.duration_s, workout.distance_m,
                workout.session_type.value, workout.terrain.value, workout.completion.value,
                workout.avg_hr, workout.avg_pace_s_per_km, workout.elevation_gain_m,
                workout.notes, workout.model_dump_json(),
            ),
        )
        if analysis is not None:
            self._exec(
                """INSERT INTO analyses (workout_id, analysis_json) VALUES (?, ?)
                   ON CONFLICT(workout_id) DO UPDATE SET analysis_json=excluded.analysis_json""",
                (workout.id, json.dumps(analysis)),
            )
        self.conn.commit()

    def list_workouts(self) -> list[dict]:
        rows = self._exec(
            """SELECT id, source_file, start_time, duration_s, distance_m, session_type,
                      terrain, completion, avg_hr, avg_pace_s_per_km, elevation_gain_m
               FROM workouts ORDER BY start_time"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_workout(self, workout_id: str) -> Workout | None:
        row = self._exec(
            "SELECT canonical_json FROM workouts WHERE id = ?", (workout_id,)
        ).fetchone()
        return Workout.model_validate_json(row["canonical_json"]) if row else None

    def get_analysis(self, workout_id: str) -> dict | None:
        row = self._exec(
            "SELECT analysis_json FROM analyses WHERE workout_id = ?", (workout_id,)
        ).fetchone()
        return json.loads(row["analysis_json"]) if row else None

    def delete_workout(self, workout_id: str) -> bool:
        """Remove a workout and its analysis. Returns True if a row was deleted."""
        cur = self._exec("DELETE FROM workouts WHERE id = ?", (workout_id,))
        self._exec("DELETE FROM analyses WHERE workout_id = ?", (workout_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # --- body ---
    def upsert_body_measurements(self, measurements: list[BodyMeasurement]) -> int:
        for m in measurements:
            self._exec(
                """INSERT INTO body_measurements
                   (timestamp, weight_kg, body_fat_pct, muscle_mass_kg, water_pct, source)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(timestamp) DO UPDATE SET
                     weight_kg=excluded.weight_kg, body_fat_pct=excluded.body_fat_pct,
                     muscle_mass_kg=excluded.muscle_mass_kg, water_pct=excluded.water_pct""",
                (m.timestamp.isoformat(), m.weight_kg, m.body_fat_pct,
                 m.muscle_mass_kg, m.water_pct, m.source),
            )
        self.conn.commit()
        return len(measurements)

    def list_body_measurements(self) -> list[BodyMeasurement]:
        rows = self._exec(
            "SELECT * FROM body_measurements ORDER BY timestamp"
        ).fetchall()
        return [
            BodyMeasurement(
                timestamp=datetime.fromisoformat(r["timestamp"]),
                weight_kg=r["weight_kg"], body_fat_pct=r["body_fat_pct"],
                muscle_mass_kg=r["muscle_mass_kg"], water_pct=r["water_pct"],
                source=r["source"] or "insmart_xls",
            )
            for r in rows
        ]

    # --- recovery ---
    def upsert_recovery(self, ctx: RecoveryContext) -> None:
        self._exec(
            """INSERT INTO recovery_context (for_date, payload_json) VALUES (?, ?)
               ON CONFLICT(for_date) DO UPDATE SET payload_json=excluded.payload_json""",
            (ctx.for_date.isoformat(), ctx.model_dump_json()),
        )
        self.conn.commit()

    def get_recovery(self, for_date: date) -> RecoveryContext | None:
        row = self._exec(
            "SELECT payload_json FROM recovery_context WHERE for_date = ?",
            (for_date.isoformat(),),
        ).fetchone()
        return RecoveryContext.model_validate_json(row["payload_json"]) if row else None

    # --- races ---
    def add_race(self, name: str, race_date: str | None, distance_m: float | None,
                 target_time_s: int | None, verified: bool = False) -> int:
        new_id = self._insert_race(name, race_date, distance_m, target_time_s, verified)
        self.conn.commit()
        return new_id

    def _insert_race(self, name, race_date, distance_m, target_time_s, verified) -> int:
        raise NotImplementedError

    def list_races(self) -> list[dict]:
        rows = self._exec("SELECT * FROM races ORDER BY race_date").fetchall()
        return [dict(r) for r in rows]


class SqliteStore(_BaseStore):
    """File-based SQLite repository. Use as a context manager or call ``close()``."""

    ph = "?"

    def __init__(self, path: str | Path = "data/coach.db"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_COMMON_TABLES.format(REAL="REAL") + _RACES_SQLITE)
        self.conn.commit()

    def _insert_race(self, name, race_date, distance_m, target_time_s, verified) -> int:
        cur = self._exec(
            "INSERT INTO races (name, race_date, distance_m, target_time_s, verified) VALUES (?,?,?,?,?)",
            (name, race_date, distance_m, target_time_s, int(verified)),
        )
        return cur.lastrowid


class PostgresStore(_BaseStore):
    """Shared PostgreSQL repository (production). Requires the ``psycopg`` driver."""

    ph = "%s"

    def __init__(self, dsn: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "PostgreSQL backend requested but 'psycopg' is not installed. "
                "Install it with: pip install 'psycopg[binary]'"
            ) from exc

        self.dsn = dsn
        self.conn = psycopg.connect(dsn, row_factory=dict_row)
        with self.conn.cursor() as cur:
            cur.execute(_COMMON_TABLES.format(REAL="DOUBLE PRECISION"))
            cur.execute(_RACES_POSTGRES)
        self.conn.commit()

    def _insert_race(self, name, race_date, distance_m, target_time_s, verified) -> int:
        row = self._exec(
            "INSERT INTO races (name, race_date, distance_m, target_time_s, verified) "
            "VALUES (?,?,?,?,?) RETURNING id",
            (name, race_date, distance_m, target_time_s, bool(verified)),
        ).fetchone()
        return row["id"]


def open_store(dsn: str | None = None) -> _BaseStore:
    """Return the appropriate store for ``dsn``.

    Resolution order when ``dsn`` is not given: ``DATABASE_URL`` env var, then
    ``COACH_DB`` env var, then the default SQLite path ``data/coach.db``.
    A ``postgres://`` / ``postgresql://`` URL selects PostgreSQL; anything else
    is treated as a SQLite file path.
    """
    dsn = dsn or os.environ.get("DATABASE_URL") or os.environ.get("COACH_DB") or "data/coach.db"
    if dsn.startswith(("postgres://", "postgresql://")):
        return PostgresStore(dsn)
    return SqliteStore(dsn)


# Backward-compatible alias: existing callers/tests use ``Store(<sqlite path>)``.
Store = SqliteStore
