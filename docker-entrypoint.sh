#!/usr/bin/env sh
# Container entrypoint. Optionally seeds the bundled regression fixtures into the
# configured database on first run (idempotent upserts), then execs the CMD.
#
# Controlled by COACH_AUTO_SEED (default "1"; set "0" to disable). The seed target
# is DATABASE_URL if set, otherwise COACH_DB (local SQLite fallback).
set -e

DB_TARGET="${DATABASE_URL:-${COACH_DB:-data/coach.db}}"

if [ "${COACH_AUTO_SEED:-1}" != "0" ]; then
    NEEDS_SEED=$(python - <<'PY'
import os
try:
    from app.persistence import open_store
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("COACH_DB", "data/coach.db")
    with open_store(dsn) as s:
        print("0" if s.list_workouts() else "1")
except Exception:
    print("1")
PY
)
    if [ "$NEEDS_SEED" = "1" ]; then
        echo "[entrypoint] Seeding regression fixtures into ${DB_TARGET} ..."
        python -m app.cli import --raw data/regression --db "$DB_TARGET" \
            --report data/processed/data_quality.json \
            || echo "[entrypoint] Seed failed (continuing without seed data)."
    else
        echo "[entrypoint] Database already populated; skipping seed."
    fi
fi

exec "$@"
