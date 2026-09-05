"""Body-composition trend analysis (PRD §17).

Uses rolling weight trends rather than single readings and flags sudden changes as
possible hydration/measurement artefacts (PRD §17).
"""

from __future__ import annotations

from ..models import BodyMeasurement

SUDDEN_CHANGE_KG = 1.5  # day-to-day swing beyond this is a likely artefact (PRD §17)


def weight_trend(measurements: list[BodyMeasurement], window: int = 5) -> dict:
    """Rolling-average weight trend with artefact flags."""
    if not measurements:
        return {"available": False, "reason": "no_measurements"}

    ordered = sorted(measurements, key=lambda m: m.timestamp)
    weights = [m.weight_kg for m in ordered]

    rolling: list[dict] = []
    artefacts: list[dict] = []
    for i, m in enumerate(ordered):
        lo = max(0, i - window + 1)
        avg = sum(weights[lo : i + 1]) / (i - lo + 1)
        rolling.append({"date": m.timestamp.isoformat(), "weight_kg": m.weight_kg, "rolling_kg": round(avg, 2)})
        if i > 0 and abs(m.weight_kg - weights[i - 1]) >= SUDDEN_CHANGE_KG:
            artefacts.append(
                {
                    "date": m.timestamp.isoformat(),
                    "delta_kg": round(m.weight_kg - weights[i - 1], 2),
                    "note": "possible hydration/measurement artefact",
                }
            )

    first_avg = sum(weights[: window]) / min(window, len(weights))
    last_avg = sum(weights[-window:]) / min(window, len(weights))
    return {
        "available": True,
        "count": len(ordered),
        "latest_kg": ordered[-1].weight_kg,
        "rolling_series": rolling,
        "trend_kg": round(last_avg - first_avg, 2),
        "artefacts": artefacts,
        "window": window,
    }
