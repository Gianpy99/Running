# AI Running Coach — Analytics Core

Deterministic, local-first running analytics platform implementing the MVP scope of
`AI_Running_Coach_PRD_v2.0`. Real-time and safety-sensitive logic is deterministic and
offline; optional OpenAI coaching provides interpretation and advisory-only planning.

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
- **Opt-in coaching**: separate workout-feedback and next-training workflows, with
  editable athlete context/races, exact prompt preview, ChatGPT export, and saved
  structured OpenAI responses. No paid calls on upload or when viewing a workout.
- **Weight & body composition**: mobile `.xls` upload with import preview, timestamp-based
  incremental updates, all export fields, selectable trends and paged reading details.

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

## Coaching

Open **Coach setup & races** to confirm your background, goals, constraints and race
calendar. A planning horizon is an exact date, including year; leave it blank to include
all races. Default athlete values used by analytics are not treated as confirmed facts.

- **After a run:** upload the watch TCX, open the session, choose **Get workout
  feedback**, and add notes/RPE. Save the notes without an API call, or request API
  feedback (which also saves them). Those reports inform next-training preparation.
- **Before a run:** choose **Prepare next training**, add recovery, available time,
  setting and the intended date.
- Preview the exact context, then **Copy for ChatGPT** or **Ask via API (paid)**.
  Existing local session summaries and deterministic plans remain unchanged.
- Successful API replies are saved automatically in the app database. Use **Saved
  coaching** in the header to reopen next-training advice by its intended training date,
  or switch to workout feedback. Older results are paged; reopening never calls OpenAI.
  The dedicated reader puts the proposed session first and keeps its close control
  visible while the response scrolls. Saved readiness is historical: recheck before running.
- The usual training window is **06:00-07:00**, with a **60-minute maximum for the whole
  session**, including warmup, recovery intervals and cooldown. The coach chooses the
  duration needed, not a fixed 30-minute run. Set a shorter per-request limit when needed;
  morning window/maximum settings are editable under **Coach setup & races**.
- Next-training preparation returns one usable schedule (or rest), without a generic
  closing question. Questions are reserved for indispensable clarifications that prevent
  a safe proposal. In **Saved coaching**, choose **Update this training** or **Answer
  questions & update advice**, enter your answers and a fresh check-in, then preview.
  Copying is free; generating a revised API response is a new explicit paid request.
  The original remains saved alongside its revision.

### Session badges and effort

The sessions table uses distinct icon/colour badges, readable names, and provenance.
Reported treadmill interval/progression/aerobic phases can replace a generic automatic
"easy" presentation. This describes structure, not physiological intensity: the canonical
classification, training-load accounting and historical analyses are not rewritten.

Effort is shown separately as **reported RPE 1-10**, with a five-level indicator.
No RPE means **Effort not logged**, not "easy"; HR or pace alone does not manufacture
an effort score. Open a workout's feedback form and **Save workout notes & RPE** to log
effort without an AI call. Table badges, workout details and the session-mix chart agree;
AI context identifies both the reported structure and the original automatic type.

See [the prompt/context design](docs/ai-coaching.md) for the evidence windows, safety
rules, provenance, limitations and refinement checklist.

**Local key:** copy `.env.example` to `.env` and paste the key after `OPENAI_API_KEY=`.
Do not use the example file for real secrets. For a native development server, explicitly
load that file (a plain `uvicorn` command does not load it automatically):

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --env-file .env
```

For local SQLite, remove/comment out `DATABASE_URL` in your `.env` and set
`COACH_DB=data/coach.db` (the example's container path is not a Windows development path).
Docker Compose loads `.env` via `env_file`. Local secrets are excluded from Git and the
Docker build context. API billing is separate from a ChatGPT subscription.

**Pi key:** use the Jenkins Secret text credential described in
[the deployment runbook](deploy/README.md#optional-openai-coaching); a Windows `.env`
does not configure the deployed Pi.

## Weight & body composition

The dashboard's **Weight & body composition** section works even before you log a run.
From your phone, tap **Import scale history (.xls)** and select the full, original INSMART
export. Review the counts/fields, then confirm the import:

- New timestamps are inserted, including older readings missing from stored history.
- Exact repeats are skipped, so you can upload the full history every time.
- Existing readings can gain previously missing columns, without changing recorded values.
- Conflicting values at the same timestamp are reported and that timestamp is left
  unchanged. Duplicate rows within a file are combined only if they agree.
- Invalid dates/weights are skipped with explicit warnings. Invalid optional values stay
  visible as original text with a warning, rather than becoming invented numbers.
- Preview is read-only; the confirmation step recomputes changes against current storage.

All 19 columns in the current export are retained, including BMI, visceral fat, bone mass,
BMR, protein, fat level, subcutaneous fat, lean body mass, body type, standard weight,
heart rate, body age, skeletal muscle and muscle ratio. Unknown future columns are kept
as original values too. `--` is shown as missing, not zero. **View reading** displays every
original column; **All fields from the latest reading** is available above the chart.
Older records imported by earlier app versions gain these details when re-uploaded.

Choose a metric and history range for the chart; the trend is a **5-reading average**,
not a five-day average. History is paged newest first; chart display is capped at the
latest 1,000 available points, with an explicit notice. The latest card uses the latest
measurement, which may be old; its full date/time is shown. Export timestamps retain
their local wall-clock meaning, matching existing stored history. Two measurements on
the same day at different times stay separate. Future-dated readings are retained and
flagged, but excluded from the dated history/chart.

This is a single-athlete tracker for original, one-sheet INSMART BIFF `.xls` exports in
kg (up to 5 MiB / 20,000 rows). `.xlsx`, renamed files, pounds, ambiguous headers and
timezone-suffixed timestamps are rejected explicitly. Uploading a file never sends it
to OpenAI: **body data remains excluded from coaching context**. Scale body-composition,
BMR and body-age figures are app estimates, not clinical measurements or target weights.
Original cell values are stored in the database; the uploaded file itself is not saved.

API: `POST /body/import` accepts multipart `file` and defaults to `preview=true`;
use `preview=false` to confirm. `GET /body` returns metric metadata, latest reading,
compact trend points and paged details (`metric`, `days`, `offset`, `limit`).
The CLI's raw-source reprocessing remains an explicit authoritative upsert; use the
dashboard's additive upload workflow for routine full-history updates.

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
