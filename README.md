# AI Running Coach — Analytics Core

Deterministic, local-first running analytics platform implementing the MVP scope of
`AI_Running_Coach_PRD_v2.0`. Real-time and safety-sensitive logic is deterministic and
offline; AI is reserved for interpretation and higher-order planning (not yet wired).

## What is implemented (MVP, deterministic)

- **Ingestion**: TCX parser → canonical `Trackpoint` model; smart-scale `.xls` reader.
- **Canonical data model**: `Athlete`, `Workout`, `Trackpoint`, `BodyMeasurement`,
  `RecoveryContext`, `WorkoutDefinition` (PRD §7).
- **Analytics engine** (PRD §9): basic metrics, time-series segmentation, HR signal
  quality flags, terrain-aware / equivalent-flat pace, aerobic efficiency, HR drift,
  transparent training load.
- **Session classification** (PRD §5.1): easy / recovery / progression / fartlek /
  interval / benchmark / family-fun / incomplete.
- **Readiness v0** (PRD §10): transparent green/amber/red rules with explanations.
- **Workout DSL + replay** (PRD §8, §11): deterministic phase state machine + replay
  engine that feeds historical trackpoints through it.
- **Persistence**: dual backend — SQLite (local/tests) or shared PostgreSQL (production),
  selected by `DATABASE_URL`.
- **Import CLI**: reprocesses raw files → workout JSON + data-quality report (PRD §23).
- **FastAPI backend**: the API sketch from PRD §20, plus a `/health` probe.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Import all raw historical files (reprocesses raw sources reproducibly, PRD §27)
running-coach import --raw ..\ --db data\coach.db --report data\processed\data_quality.json

# Run the API
uvicorn app.main:app --app-dir backend --reload

# Tests / regression suite
pytest
```

## Layout

```
backend/app/{api,models,services,analytics,ingestion,training,ai}
data/{raw,processed,regression}
tests/{unit,regression,replay,synthetic}
docs/
```

## Deployment (Family Portal / Raspberry Pi)

Containerised and deployed like the other family-portal apps (MyGarage, AudibleConverter):
a `Dockerfile` + `Jenkinsfile` build and run the container on the Pi via Jenkins, backed by
the shared PostgreSQL and published at `running.borrellofamily.co.uk` (host port `8094`).

- Local image test: `docker compose up --build` (copy `.env.example` → `.env` first).
- Full step-by-step runbook (DB creation, Jenkins job/secret, Caddy route, DNS):
  see [deploy/README.md](deploy/README.md).

