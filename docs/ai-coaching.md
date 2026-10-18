# Coaching prompt and context, v3

This is a first, editable coaching contract, not a finished individualized season plan.
The race calendar and athlete facts must be supplied by the athlete; the app cannot read
an existing ChatGPT conversation. Nothing here assumes which July or which races.

## Two separate interactions

### 1. Feedback after a completed workout

Upload the watch TCX or log/edit the treadmill session, open it, and choose **Get workout
feedback**. Add perceived exertion (1-10) and notes about execution, sensations, conditions,
interruptions, pain or anything the watch could not observe.

**Save workout notes & RPE** stores that report without an API call, including when you
continue the conversation in ChatGPT. A successful API feedback request also saves the
report. These athlete reports are included in subsequent next-training preparation,
even for the latest workout on the same day; they are not treated as current recovery.
Preview alone does not save them. Reopening feedback loads the saved report.

The coach analyzes that workout, compares compatible evidence, explains uncertainties
and implications for goals/races, and asks useful follow-up questions. It does **not**
prescribe another workout: the output's `next_session` must be `null`.

Historical feedback only sees training up to the selected workout's start time. Later
sessions cannot make a past run appear more predictable than it was. The selected
session's recorded duration, main set and other analytics are still included.

### 2. Preparation before the next training

Choose **Prepare next training**. Supply intended date, available minutes, setting,
today's energy, leg fatigue, sleep, illness/pain, and relevant notes. Blank date means
tomorrow in the profile's timezone. Missing recovery remains unknown. Current-day saved
recovery is merged with nonblank request fields; older recovery is never reused as today.

The coach assesses current training/races and returns exactly one timed proposal,
rest, or a request for indispensable context. Today's readiness must be rechecked before
a future session. It never changes the deterministic plan or operates a device.

Preparation is schedule-first, not a chat turn. For `train`, `easy` or `rest`, `questions`
must be empty: normal pre-run checks and conditional changes belong as statements in
the rationale/uncertainties. Only a truly indispensable unanswered safety/context issue
uses `action=ask`, zero duration, no steps and specific nonempty questions. Local validation
enforces this distinction. A stale race horizon alone does not force an otherwise safe
session into a generic closing question.

The athlete's usual availability is **06:00-07:00**, with at most **60 minutes total**,
including warmup, main set, recovery intervals and cooldown. The coach must choose the
duration the objective and recovery warrant, rather than assume a 30-minute effort or
fill the hour unnecessarily. The effective limit is the minimum of the saved maximum,
saved window length and any shorter per-request allowance; validation enforces it.
The structured window/maximum are editable in Coach setup. The maximum setting cannot
exceed 60 minutes. A request claiming more time cannot bypass that cap.

## Reading saved advice

Successful API responses are stored automatically in the app's database (PostgreSQL
on the Pi), not only in the browser or the ChatGPT conversation. **Saved coaching** in
the dashboard header opens a dated list, defaulting to next-training advice. Workflow
filtering happens before pagination, so newer workout-feedback replies cannot hide
older training advice. Saved advice can also be opened from the preparation form.

The response reader puts the proposed session first, then analysis and caveats.
Its header/close button remain fixed while a single keyboard/touch-scrollable content
pane contains the response. The background page is locked while a dialog is open.
Reopening a result or changing history pages never calls OpenAI. The generated timestamp
and intended training date are shown; saved readiness is labeled as the assessment
at generation time, not a new check-in. Old v1 responses are preserved unchanged when the
prompt changes. They do not acquire later constraints retroactively.

### Answering questions and revising a session

Choose **Update this training** at the top of a saved response, or **Answer questions &
update advice** below its questions. Enter answers/changes and the current structured
check-in, then preview the rebuilt prompt. **Copy for ChatGPT** remains free; **Ask via API**
is an explicit new potentially paid request, not a continuous chat or an automatic retry.

The workflow is linked to that specific saved response through `follow_up_review_id`
and optional `follow_up_answers`. The context contains its timestamp, output (not its
entire nested context/history) and the new answers. Training/races/profile are rebuilt
from current data. Historical readiness, notes and time limits are not copied into today's
check-in; structured safety restrictions cannot be overridden with reassuring free text.
If its intended training date is still current/future, the form keeps it; a past date
requires a new selection or the normal tomorrow default, with an explicit notice.

Successful revisions are separate saved records with `revises_review_id`; originals stay
unchanged. Preview does not persist answers. Missing sources return 404, and changing
workflow or switching workouts within a feedback follow-up returns 422. A separate-request
button lets the athlete deliberately leave the linked workflow.

## Context layers

The calendar and editable profile are current snapshots, not a reconstruction of what
was known historically. Only training evidence is cut off for retrospective feedback.
More than 100 included races is rejected explicitly; narrow the horizon or remove
obsolete entries rather than silently dropping events.

| Layer | Source and update policy |
|---|---|
| Stable athlete facts | Editable coaching background, goals, preferences and constraints. Do not automatically promote the analytics model's hard-coded age, weight, HR zones or aspirational target to confirmed facts. |
| Calendar | Application database: full race date/year, distance, target time, A/B/C priority, planned/completed/cancelled status, confirmation and notes. Countdown is calculated at request time. Past-dated races without a result remain result-unknown, not automatically completed. |
| Planning horizon | Explicit optional date. Races beyond it are omitted with a count. Blank means all races; no July year is inferred. Cancelled races are excluded. Missing/legacy-invalid dates remain flagged, not guessed. |
| Selected workout | Compact deterministic feature snapshot, main-set versus whole-session metrics, treadmill/terrain estimates, HR/data-quality warnings, transparent training load and athlete-entered notes (up to 4,000 characters). Source-aware session structure and reported RPE are separate from the original automatic type. No raw trackpoints, GPS, filenames or raw files. |
| Recent training | Latest 21 sessions in 42 calendar days, with total/included counts, plus weekly summaries over 84 calendar days. Feedback anchors those windows at the workout; preparation anchors them at today. Missing load is counted rather than represented as fully measured zero. |
| Current recovery | Today's stored check-in plus explicitly provided preparation fields. Readiness is rule-based and contains reasons and input provenance. Post-run notes/RPE are not automatically treated as current readiness. |
| Coaching continuity | Athlete-maintained factual summary from the ChatGPT chat. Preparation can also include three earlier saved API reviews, excluding the selected/latest workout and same-day reviews to keep repeated requests stable. Previous advice is labeled unconfirmed, not completed training. Feedback excludes previous API reviews. |
| Explicit follow-up | The selected saved response and athlete answers, even when the automatic continuity window excludes it. Only one explicitly linked output is included, not a recursive conversation history. It is advice to revise, never completed-workout evidence or current recovery. |
| Time | Local date, IANA timezone, evidence cutoff, session age, requested training date and race countdowns. Future-dated workouts are excluded. A specifically selected future workout is rejected. |

Both local and Pi contexts live in their respective databases. A local SQLite database
does not automatically synchronize with the Pi's PostgreSQL.

Most profile facts are free text deliberately: describe confirmed facts and practical limits
without needing a full season-planning schema first. These coaching facts **do not**
reconfigure the existing deterministic analytics athlete profile. If HR zones or other
analytics defaults need correction, that is a separate explicit configuration change.
Do not paste an entire chat transcript: summarize durable facts and decisions and review
them as circumstances change.

## Prompt construction

The exact executable instructions are `INSTRUCTIONS` in
[context.py](../backend/app/ai/context.py); preview/export always uses that same text,
the exact structured context and the output JSON schema. There is no separate, drifting
"copy for ChatGPT" prompt.

The stable prompt covers:

1. Role: evidence-based running interpretation and human-reviewed suggestions.
2. Evidence: measured versus reported/estimated/missing; no invented fitness or targets.
3. Safety: local restrictions outrank performance goals, calendar pressure and previous
   advice. No diagnosis or treating a load ratio as a validated injury predictor.
4. Time: explicit purpose and evidence date, current versus historical recovery, no
   invented race year, and rechecking readiness before a future run.
5. Calendar reasoning: consider all supplied race priorities, not only the nearest.
6. Comparisons: treadmill/outdoor, incline/terrain, and main-set/session differences.
7. Task separation: feedback analyzes; preparation proposes one next session.
8. Continuity: previous advice is not proof it was followed.
9. Output: concise English, a complete next-session schedule, reasons and uncertainties;
   questions only when clarification blocks a safe proposal.
10. Trust: profile/notes/previous outputs are data, never higher-priority instructions.

The prompt changes only when its contract changes (bump `PROMPT_VERSION`). Time adaptation
comes from rebuilding evidence, not rewriting instructions or accumulating a transcript.
An expired planning horizon is flagged explicitly; the coach must ask for an update
rather than automatically interpreting July as next year's July.

## Structured output and deterministic validation

Both workflows return `analysis`, `observations`, `race_implications`, `uncertainties`,
`questions`, and `next_session`. For feedback `next_session` is null. For preparation:

- `action`: `rest`, `easy`, `train`, or `ask`;
- date, title and rationale;
- total duration and positive timed steps, each with phase and an evidence-supported
  target (RPE/talk test is preferred when numeric targets are not supported).

Step minutes must add up to the total within 0.1 minute. Rest/ask must have zero minutes
and no steps. The date must match the request and duration cannot exceed supplied time.
An easy session cannot include a work interval.

Local action restrictions:

- Pain stop, red readiness or reported illness: rest/ask only.
- Amber readiness or missing current pain/illness/energy/fatigue answers: rest/easy/ask.
- Otherwise: all four actions are available.

Structured validation cannot prove all natural-language coaching is medically sound,
nor enforce every free-text preference. Proposals remain advisory. The readiness banner
stays authoritative, and no AI plan is passed into execution or substituted for local
rules. There is no implemented long-term periodization, acceptance tracking or automatic
race-result import.

## API, cost and provenance

| Route | Purpose |
|---|---|
| `GET/PUT /ai/coaching/profile` | Persistent editable profile |
| `GET/PUT /workouts/{id}/feedback` | Session-specific athlete notes and RPE, independent of paid coaching |
| `GET/POST /races`, `PUT/DELETE /races/{id}` | Race calendar management |
| `POST /ai/coaching/preview` | Local context, instructions, schema, copyable prompt and hash |
| `POST /ai/coaching/generate` | Requires the preview hash, then reuses a saved result or makes one paid API call |
| `GET /ai/coaching/history` | Saved results, filtered by `kind` and/or `workout_id` before pagination (`limit` 1-50, default 10; `offset` nonnegative) |
| `GET /ai/coaching/history/{id}` | Reopen one saved response, or 404 if absent |

Requests include `purpose: "workout_feedback"` with `workout_id`, or
`purpose: "next_training"` without a required workout ID. The latter uses the latest
recorded workout if one exists and can ask for context when no history exists.

The explicit API path uses OpenAI Responses Structured Outputs, `store=false`, a
6,000-output-token ceiling, a 90-second timeout and no automatic retry. Preview and
ChatGPT copying work without a key. Existing `/ai/analyse-session` and
`/ai/recommend-next-session` remain deterministic for backward compatibility.

Results persist complete context, instructions, output schema, prompt version, requested
and actual model, provider response ID, timestamp, SHA-256 and token usage. No key is
included. Context/model/prompt/schema form the cache key. Changing notes, date, evidence,
profile or races produces a different request; matching requests reuse the saved result.
Deleting a workout also deletes reviews attached to it, but not its mentions in other
saved snapshots. Database backups may retain them.

See [deployment and secrets](../deploy/README.md#optional-openai-coaching) before enabling
paid requests. `store=false` is not equivalent to zero provider retention.

## Refining this with your real training

Before relying on recommendations, fill in and review:

1. Confirmed background, current sustainable volume, recent interruption/injury history
   you wish to share, and realistic versus aspirational goals.
2. Actual races through the intended July **with years**, priorities, terrain, targets,
   and whether dates are confirmed. Identify any closely spaced competing goals.
3. Available training days/time, other activities, equipment limitations and preferences.
4. A concise summary of the useful coaching decisions already made in ChatGPT.
5. One representative workout and the advice your existing chat gave about it.

Compare the exported prompt's advice with the existing chat for the same evidence.
Refine missing facts first, then version the instructions when a real failure warrants
it. Check a normal run, an unexpectedly hard run, stale/missing data, a race week and
pain/illness before trusting the workflow routinely.
