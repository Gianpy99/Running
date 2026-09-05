"""Canonical data model (PRD §7).

Every model is source-independent. Raw files remain the authoritative measurement
source (PRD §27); these structures are the reproducible canonical projection.
"""

from .enums import (
    CompletionStatus,
    PhaseType,
    QualityFlag,
    ReadinessLevel,
    SessionType,
    TerrainType,
)
from .athlete import Athlete
from .trackpoint import Trackpoint
from .workout import Workout
from .body import BodyMeasurement
from .recovery import RecoveryContext
from .definition import AdaptiveRule, Phase, WorkoutDefinition

__all__ = [
    "Athlete",
    "Trackpoint",
    "Workout",
    "BodyMeasurement",
    "RecoveryContext",
    "WorkoutDefinition",
    "Phase",
    "AdaptiveRule",
    "CompletionStatus",
    "PhaseType",
    "QualityFlag",
    "ReadinessLevel",
    "SessionType",
    "TerrainType",
]
