"""Transparent training load (PRD §9.7).

Duration/HR/RPE-based load. Family/fun and interrupted sessions are still computed but
carry their classification so downstream logic can keep them separate (PRD §9.7).
"""

from __future__ import annotations

from ..models import Athlete, Workout
from ..models.enums import CompletionStatus, SessionType


def training_load(workout: Workout, athlete: Athlete, rpe: int | None = None) -> dict:
    """A transparent HR- or RPE-weighted duration load (arbitrary but reproducible units).

    Preference order:
      1. HR-weighted: minutes x mean %HRmax (when reliable HR exists).
      2. RPE-weighted: minutes x RPE (when supplied and HR unavailable).
      3. Duration-only fallback.
    """
    minutes = workout.duration_s / 60.0
    hrs = [p.hr_bpm for p in workout.trackpoints if p.hr_bpm is not None and not p.is_hr_suspect]
    hr_max = athlete.estimated_max_hr()

    method = "duration_only"
    load = round(minutes, 1)
    intensity_factor = None

    if hrs:
        mean_pct = (sum(hrs) / len(hrs)) / hr_max
        intensity_factor = round(mean_pct, 3)
        load = round(minutes * mean_pct * 100, 1)
        method = "hr_weighted"
    elif rpe is not None:
        intensity_factor = round(rpe / 10.0, 3)
        load = round(minutes * rpe, 1)
        method = "rpe_weighted"

    return {
        "method": method,
        "load": load,
        "minutes": round(minutes, 1),
        "intensity_factor": intensity_factor,
        "session_type": workout.session_type.value,
        "completion": workout.completion.value,
        # Kept separate per PRD §9.7 so these don't distort planned-training trends.
        "counts_toward_planned_load": workout.session_type
        not in (SessionType.FAMILY_FUN, SessionType.INCOMPLETE)
        and workout.completion != CompletionStatus.INTERRUPTED,
        "hr_max_used": hr_max,
    }
