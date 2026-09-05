"""AI layer (PRD §12).

The LLM is used only for interpretation/narrative — never for safety-critical arithmetic
or real-time thresholds (PRD §12). This module:
  * builds a minimal feature snapshot (send the minimum necessary data),
  * produces a structured, machine-consumable result,
  * records provenance (prompt version, model, snapshot, output) for reproducibility,
  * falls back to a deterministic template when no API key is configured, so the
    system is fully functional offline.

Actual OpenAI Responses API wiring is intentionally deferred until deterministic
analytics are stable (PRD §23 "Integrate OpenAI only after deterministic analytics").
"""

from .narrator import build_feature_snapshot, explain_session, recommend_next_session

__all__ = ["build_feature_snapshot", "explain_session", "recommend_next_session"]
