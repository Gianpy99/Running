"""Replay engine: feed historical trackpoints into the live state machine (PRD §11, §19).

This is the bridge that lets recorded sessions act as regression fixtures for the live
coach — the same trackpoints must always produce the same event stream.
"""

from __future__ import annotations

from ..models import Workout, WorkoutDefinition
from ..models.enums import QualityFlag
from .state_machine import CoachEvent, LiveCoach


def replay_workout(
    definition: WorkoutDefinition, workout: Workout, downgrade_to_easy: bool = False
) -> list[CoachEvent]:
    """Replay a recorded workout through the coach and collect all emitted events."""
    coach = LiveCoach(definition=definition, downgrade_to_easy=downgrade_to_easy)
    events: list[CoachEvent] = list(coach.start())
    for p in workout.trackpoints:
        sensor_ok = QualityFlag.OK in p.quality or not p.is_hr_suspect
        events.extend(coach.update(p.elapsed_s, p.hr_bpm, p.speed_mps, sensor_ok=sensor_ok))
        if coach.finished:
            break
    # Ensure a completion event even if the recording ends slightly short.
    if not coach.finished and workout.trackpoints:
        total_s = sum((ph.duration_min or 0) * 60 for ph in definition.phases)
        events.extend(coach.update(total_s, None, None, sensor_ok=False))
    return events
