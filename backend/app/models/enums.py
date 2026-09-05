"""Controlled vocabularies for the canonical model."""

from __future__ import annotations

from enum import Enum


class SessionType(str, Enum):
    """Session classification (PRD §5.1)."""

    EASY = "easy"
    RECOVERY = "recovery"
    PROGRESSION = "progression"
    FARTLEK = "fartlek"
    INTERVAL = "interval"
    BENCHMARK = "benchmark"
    FAMILY_FUN = "family_fun"
    INCOMPLETE = "incomplete"
    UNCLASSIFIED = "unclassified"


class CompletionStatus(str, Enum):
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class TerrainType(str, Enum):
    TREADMILL = "treadmill"
    FLAT_OUTDOOR = "flat_outdoor"
    HILLY_OUTDOOR = "hilly_outdoor"
    UNKNOWN = "unknown"


class QualityFlag(str, Enum):
    """Trackpoint / interval quality annotations (PRD §9.3)."""

    OK = "ok"
    HR_IMPLAUSIBLE_JUMP = "hr_implausible_jump"
    HR_FLATLINE = "hr_flatline"
    HR_MISSING = "hr_missing"
    HR_ABRUPT_RECOVERY = "hr_abrupt_recovery"
    GPS_JUMP = "gps_jump"
    WATCH_REPOSITIONED = "watch_repositioned"


class PhaseType(str, Enum):
    """Workout DSL phase types (PRD §8)."""

    WARMUP = "warmup"
    AEROBIC = "aerobic"
    PROGRESSION = "progression"
    INTERVAL = "interval"
    RECOVERY = "recovery"
    COOLDOWN = "cooldown"


class ReadinessLevel(str, Enum):
    """Readiness traffic light (PRD §10)."""

    GREEN = "green"
    AMBER = "amber"
    RED = "red"


class SegmentType(str, Enum):
    """Time-series segment labels (PRD §9.2)."""

    WARMUP = "warmup"
    STEADY_AEROBIC = "steady_aerobic"
    MODERATE = "moderate"
    FAST = "fast"
    RECOVERY = "recovery"
    WALKING = "walking"
    COOLDOWN = "cooldown"
    PAUSED = "paused"
