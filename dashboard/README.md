# dashboard/ (deferred — Sprint 2)

React/TypeScript web dashboard (PRD §13, §22). Not yet implemented.

The deterministic backend already exposes everything the dashboard needs via the
FastAPI endpoints (PRD §20), so this can be built without further backend work:

- Home: `GET /readiness`, `GET /workouts` (last), `GET /training-load`.
- Workout detail: `GET /workouts/{id}`, `GET /workouts/{id}/analysis` (route, pace, HR,
  elevation, segments, quality warnings).
- Fitness/trends: `GET /trends/aerobic-efficiency`, `GET /trends/hr-drift`,
  `GET /trends/body-weight`.
- Races/taper: `GET /races`. Data-quality view: `GET /data-quality`.
- AI explanations: `POST /ai/analyse-session`.
