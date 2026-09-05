# Architecture (PRD v2.0)

Deterministic, local-first. Real-time and safety logic is deterministic; AI is confined
to interpretation and provenance-wrapped suggestions (PRD §1, §12).

```mermaid
flowchart LR
    subgraph Ingestion
      TCX[TCX/GPX/FIT] --> P[tcx_parser]
      XLS[Smart scale .xls] --> SR[scale_reader]
    end
    P --> CM[Canonical model:\nWorkout/Trackpoint]
    SR --> BM[BodyMeasurement]
    CM --> AE[Analytics engine\nmetrics/segmentation/quality/\nterrain/efficiency/drift/load]
    AE --> CL[Session classification]
    CL --> ST[(SQLite Store)]
    AE --> ST
    BM --> ST
    ST --> API[FastAPI §20]
    RC[RecoveryContext] --> RD[Readiness v0]
    ST --> RD
    RD --> PL[Planner / adaptive\ndowngrade]
    DSL[Workout DSL §8] --> SM[Live state machine]
    CM --> RP[Replay engine] --> SM
    AE --> AI[AI narrator\nprovenance envelope]
    API --> DASH[dashboard/ (deferred)]
    SM --> WEAR[wearos/ (deferred, spike-gated)]
```

## Layers

| Layer | Package | PRD |
|---|---|---|
| Ingestion | `app.ingestion` | §5.1, §6 |
| Canonical model | `app.models` | §7 |
| Analytics (deterministic) | `app.analytics` | §9 |
| Services (classification, readiness, trends, pipeline) | `app.services` | §5.1, §10, §17 |
| Training (DSL, state machine, replay, planner) | `app.training` | §8, §11 |
| Persistence | `app.persistence` | §6 |
| AI (interpretation only) | `app.ai` | §12 |
| API | `app.api` | §20 |

## Provenance & reproducibility (PRD §4, §27)

- Raw files are authoritative; the DB stores the canonical projection plus each raw
  source filename. Re-running `import` reproduces identical analyses.
- Every derived metric exposes the thresholds/model it used.
- AI outputs are wrapped with prompt version, model, feature-snapshot hash and output.

## Deferred (validation-gated)

- `dashboard/` (React/TS) — Sprint 2 (§22).
- `wearos/` (Kotlin) — requires the coexistence feasibility spike first (§5.3, §22, §24).
- OpenAI Responses API wiring — only after deterministic analytics are stable (§23).
