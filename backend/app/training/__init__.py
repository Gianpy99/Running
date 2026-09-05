"""Training subsystem: DSL loading, live state machine, replay, planning (PRD §8, §11)."""

from .dsl import load_definition, standard_treadmill_session
from .state_machine import CoachEvent, LiveCoach
from .replay import replay_workout
from .planner import adapt_definition, generate_next_session

__all__ = [
    "load_definition",
    "standard_treadmill_session",
    "CoachEvent",
    "LiveCoach",
    "replay_workout",
    "adapt_definition",
    "generate_next_session",
]
