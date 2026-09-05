# wearos/ (deferred — spike-gated)

Wear OS live coach in Kotlin/Android (PRD §5.3, §11).

**Blocked by a technical spike** (PRD §5.3, §22 Sprint 7, §24): establish whether a
custom Wear OS app can coexist with the native exercise recorder before the architecture
is frozen. Do not build the client until this is validated.

The deterministic coaching logic already exists and is reference behaviour for the
eventual port:

- `backend/app/training/state_machine.py` — the offline live-coach state machine
  (phase transitions, cues, safe HR-based adaptation; extreme HR ignored when sensor
  quality is poor).
- `backend/app/training/replay.py` — replays recorded sessions through the same machine,
  making historical trackpoints regression fixtures for the live coach (PRD §19).

The Kotlin implementation must reproduce these deterministic transitions exactly.
