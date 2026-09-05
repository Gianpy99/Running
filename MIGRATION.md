# Migration recap — move to home computer

Snapshot written: 2026-09-04. Follow this to zip here and continue at home with **zero data loss**.

## Current state

- **App**: AI Running Coach (FastAPI + deterministic analytics core).
- **Database**: `ai-running-coach/data/coach.db` (SQLite, ~9.5 MB) — this is the single source of
  truth and already contains everything:
  - **19 workouts** (99.8 km, 791 min) — includes today's session `20260904T060242` (easy, 5.71 km)
  - **29 body measurements**
  - Recovery context / races (whatever you've entered)
- **New feature added this session**: single-file upload.
  - Endpoint: `POST /workouts/upload` (multipart `.tcx`) in
    [backend/app/api/routes.py](backend/app/api/routes.py) — parses, classifies, analyses, and
    persists one run; re-uploading an existing run updates it instead of duplicating.
  - Dashboard **"＋ Upload run (.tcx)"** button in
    [backend/app/api/static/index.html](backend/app/api/static/index.html).
  - New dependency `python-multipart` added to [pyproject.toml](pyproject.toml).

## What to zip

Zip the whole `C:\Development\Running` folder, but you can safely **exclude** (all rebuildable):

- `.venv/`  ← virtual env, recreate at home
- `**/__pycache__/`, `*.pyc`
- `**/*.egg-info/`, `.pytest_cache/`

**Must keep** (not all are in git — the DB is `.gitignore`d, so a zip is the reliable transfer):

- `ai-running-coach/data/coach.db`  ← all your imported data
- `ai-running-coach/data/regression/*.tcx`  ← raw source runs (lets you re-import from scratch)
- All source under `ai-running-coach/`

PowerShell one-liner to create a clean zip:

```powershell
cd C:\Development
$src = "C:\Development\Running"
$tmp = "C:\Development\Running_migrate"
robocopy $src $tmp /E /XD .venv __pycache__ .pytest_cache /XF *.pyc | Out-Null
Compress-Archive -Path "$tmp\*" -DestinationPath "C:\Development\running-coach-migration.zip" -Force
Remove-Item $tmp -Recurse -Force
```

## Set up at home

```powershell
# 1. Unzip, then from the repo root:
cd <unzipped>\Running\ai-running-coach

# 2. Fresh virtual env (Python 3.11+; here it was 3.12)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install the app + dev tools (installs fastapi, uvicorn, pydantic, xlrd, python-multipart)
pip install -e ".[dev]"

# 4. Run the API (data/coach.db is picked up automatically)
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 — you should immediately see all 18 sessions.

## If the DB is ever lost / you want a clean rebuild

The raw `.tcx` files are kept, so you can regenerate `coach.db` from scratch:

```powershell
running-coach import --raw data\regression --db data\coach.db --report data\processed\data_quality.json
```

or, with the server running, call `POST /workouts/import` with body `{"raw_dir": "<path to .tcx folder>"}`.

## Quick verification at home

```powershell
python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/summary'))['totals'])"
# expect: {'workouts': 19, 'distance_km': 99.8, ...}
pytest   # regression + unit suite should pass
```

## Notes / gotchas

- The DB path defaults to `data/coach.db`; override with the `COACH_DB` env var if you move it.
- On Windows PowerShell 5.1, `Invoke-RestMethod` has no `-Form`; use `curl.exe -F` or `urllib` for uploads.
- Nothing here depends on the network or an AI service — analytics are fully offline/deterministic.
