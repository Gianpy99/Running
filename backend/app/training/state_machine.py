"""Deterministic local live-coach state machine (PRD §5.3, §11, §26).

Offline-capable and fully deterministic: given the same inputs it always emits the same
cues. The LLM is never in this loop (PRD §12). Extreme HR is ignored when sensor quality
is poor (PRD §12, §18).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..models import WorkoutDefinition
from ..models.enums import PhaseType


class EventKind(str, Enum):
    PHASE_START = "phase_start"
    CUE = "cue"
    ADAPTATION = "adaptation"
    SAFETY = "safety"
    COMPLETE = "complete"


@dataclass
class CoachEvent:
    at_s: float
    kind: EventKind
    message: str
    phase: str | None = None
    vibrate: bool = False
    audio: bool = False
    display: bool = True


@dataclass
class LiveCoach:
    """Runs a `WorkoutDefinition` from streamed sensor updates.

    Downgrade (e.g. from a readiness red/amber decision, PRD §26) is applied at start:
    it replaces non-easy phases with easy aerobic targets.
    """

    definition: WorkoutDefinition
    downgrade_to_easy: bool = False

    phase_index: int = field(default=0, init=False)
    phase_start_s: float = field(default=0.0, init=False)
    started: bool = field(default=False, init=False)
    finished: bool = field(default=False, init=False)
    _hr_breach_s: float = field(default=0.0, init=False)
    _last_t: float = field(default=0.0, init=False)

    # Sustained breach (seconds) before an adaptation cue fires — avoids twitchy cues.
    breach_hold_s: float = 20.0

    def _phase_bounds_s(self) -> list[tuple[float, float]]:
        bounds = []
        t = 0.0
        for p in self.definition.phases:
            dur = (p.duration_min or 0.0) * 60.0
            bounds.append((t, t + dur))
            t += dur
        return bounds

    def _phase_label(self, idx: int) -> str:
        p = self.definition.phases[idx]
        if self.downgrade_to_easy and p.type not in (PhaseType.WARMUP, PhaseType.COOLDOWN):
            return f"{PhaseType.AEROBIC.value} (downgraded)"
        return p.type.value

    def start(self) -> list[CoachEvent]:
        self.started = True
        first = self.definition.phases[0]
        msg = "We're keeping this aerobic today" if self.downgrade_to_easy else f"Starting {first.type.value}"
        return [
            CoachEvent(0.0, EventKind.PHASE_START, msg, phase=self._phase_label(0),
                       vibrate=True, audio=True)
        ]

    def update(self, elapsed_s: float, hr: int | None, speed_mps: float | None,
               sensor_ok: bool = True) -> list[CoachEvent]:
        """Feed one sensor sample; return any events triggered at this time."""
        if not self.started:
            return self.start()
        if self.finished:
            return []

        events: list[CoachEvent] = []
        bounds = self._phase_bounds_s()
        total = bounds[-1][1] if bounds else 0.0
        dt = max(elapsed_s - self._last_t, 0.0)
        self._last_t = elapsed_s

        # Phase transition on elapsed time crossing the phase boundary.
        while self.phase_index < len(bounds) - 1 and elapsed_s >= bounds[self.phase_index][1]:
            self.phase_index += 1
            self.phase_start_s = bounds[self.phase_index][0]
            self._hr_breach_s = 0.0
            events.append(
                CoachEvent(elapsed_s, EventKind.PHASE_START,
                           self._phase_message(self.phase_index),
                           phase=self._phase_label(self.phase_index),
                           vibrate=True, audio=True)
            )

        # Completion.
        if elapsed_s >= total and not self.finished:
            self.finished = True
            events.append(CoachEvent(elapsed_s, EventKind.COMPLETE, "Workout complete — nice work.",
                                     vibrate=True, audio=True))
            return events

        # Adaptive HR rules — only trusted when the HR sensor is reliable (§12, §18).
        phase = self.definition.phases[self.phase_index]
        target = None if self.downgrade_to_easy else phase.hr_target
        if sensor_ok and hr is not None and target is not None:
            lo, hi = target
            if hr > hi + phase.tolerance_bpm:
                self._hr_breach_s += dt
                if self._hr_breach_s >= self.breach_hold_s:
                    self._hr_breach_s = 0.0
                    events.append(CoachEvent(elapsed_s, EventKind.ADAPTATION,
                                             "Ease back slightly", phase=self._phase_label(self.phase_index),
                                             vibrate=True))
            elif hr < lo - phase.tolerance_bpm:
                self._hr_breach_s = 0.0  # below target is not urgent; no nag
            else:
                self._hr_breach_s = 0.0

        return events

    def _phase_message(self, idx: int) -> str:
        p = self.definition.phases[idx]
        if self.downgrade_to_easy and p.type not in (PhaseType.WARMUP, PhaseType.COOLDOWN):
            return "We're keeping this aerobic today"
        return {
            PhaseType.WARMUP: "Easy warm-up",
            PhaseType.AEROBIC: "Main block starts",
            PhaseType.PROGRESSION: "Lift the pace a little",
            PhaseType.INTERVAL: "Work interval — go",
            PhaseType.RECOVERY: "Recover",
            PhaseType.COOLDOWN: "Cool down, ease off",
        }.get(p.type, f"Starting {p.type.value}")
