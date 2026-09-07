"""Free-text treadmill session logging (PRD §15).

Treadmill runs have no GPS, so the athlete instead describes what they did, one phase
per line, e.g.::

    10 min warmup at 4mph
    25 min at 4.7mph with 1%
    5 min at 5mph with 1%
    5 min cooldown

We parse that into the structured `WorkoutDefinition` DSL and project it onto a canonical
`Workout` with synthesized trackpoints so the deterministic analytics pipeline treats it
like any other session. Values are user-reported, not measured (terrain = treadmill).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..models import Phase, Trackpoint, Workout, WorkoutDefinition
from ..models.enums import PhaseType

MPH_TO_MPS = 0.44704
KMH_TO_MPH = 1.0 / 1.60934
_TRACKPOINT_STEP_S = 10  # resolution of the synthesized time-series
_COOLDOWN_STEPS = 5  # a speed-less cooldown ramps to a stop over this many minute-steps

# Duration in hours / minutes / seconds. Minutes are the common case.
_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b",
    re.IGNORECASE,
)
_SPEED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mph|km/?h|kmh|kph)\b", re.IGNORECASE)
_INCLINE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

_PHASE_KEYWORDS = [
    (("warmup", "warm up", "warm-up"), PhaseType.WARMUP),
    (("cooldown", "cool down", "cool-down"), PhaseType.COOLDOWN),
    (("recovery", "recover"), PhaseType.RECOVERY),
    (("interval", "sprint", "hard"), PhaseType.INTERVAL),
    (("progression", "build"), PhaseType.PROGRESSION),
]


def _duration_to_minutes(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        return value * 60.0
    if unit in ("s", "sec", "secs", "second", "seconds"):
        return value / 60.0
    return value  # minutes (min / mins / minute / minutes / m)


def _speed_to_mph(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit == "mph":
        return value
    return value * KMH_TO_MPH  # km/h family


def _phase_type(line: str) -> PhaseType:
    lowered = line.lower()
    for keywords, phase_type in _PHASE_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return phase_type
    return PhaseType.AEROBIC


def _phase_speed_mps(
    phase: Phase, t_in_phase_s: float, prev_speed_mph: float | None
) -> float | None:
    """Instantaneous speed for a phase at ``t_in_phase_s`` seconds in.

    A cooldown with no stated speed decelerates from the previous phase's speed, stepping
    down by (previous speed / 5) each minute until it reaches a walk/stop.
    """
    if phase.speed_mph:
        return phase.speed_mph * MPH_TO_MPS
    if phase.type == PhaseType.COOLDOWN and prev_speed_mph:
        gap = prev_speed_mph / _COOLDOWN_STEPS
        minute = int(t_in_phase_s // 60)
        speed_mph = prev_speed_mph - gap * (minute + 1)
        return speed_mph * MPH_TO_MPS if speed_mph > 0 else None
    return None


def parse_treadmill_log(text: str) -> WorkoutDefinition:
    """Parse a multi-line treadmill description into a `WorkoutDefinition`.

    Each non-blank line becomes one phase. A duration is required per line; speed and
    incline are optional. Lines starting with '#' are treated as comments.
    """
    phases: list[Phase] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        dur_match = _DURATION_RE.search(line)
        if not dur_match:
            raise ValueError(f"no duration found in line: {raw_line!r}")
        duration_min = _duration_to_minutes(float(dur_match.group(1)), dur_match.group(2))

        speed_mph = None
        speed_match = _SPEED_RE.search(line)
        if speed_match:
            speed_mph = round(_speed_to_mph(float(speed_match.group(1)), speed_match.group(2)), 2)

        incline_pct = None
        incline_match = _INCLINE_RE.search(line)
        if incline_match:
            incline_pct = float(incline_match.group(1))

        phases.append(
            Phase(
                type=_phase_type(line),
                duration_min=duration_min,
                speed_mph=speed_mph,
                incline_pct=incline_pct,
            )
        )

    if not phases:
        raise ValueError("no workout phases found in description")
    return WorkoutDefinition(name="Treadmill session", phases=phases)


def build_treadmill_workout(
    text: str,
    start_time: datetime | None = None,
    avg_hr: int | None = None,
    source_file: str | None = None,
) -> Workout:
    """Build a canonical `Workout` from a free-text treadmill description.

    Synthesizes a per-phase trackpoint series (constant speed within each phase) so the
    standard analytics pipeline can run. The original text is preserved verbatim in
    `notes` as the athlete's own account of the session.
    """
    definition = parse_treadmill_log(text)

    if start_time is None:
        start_time = datetime.now(timezone.utc)
    elif start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    points: list[Trackpoint] = []
    elapsed_s = 0.0
    distance_m = 0.0
    prev_speed_mph: float | None = None
    for phase in definition.phases:
        phase_s = (phase.duration_min or 0.0) * 60.0
        t = 0.0
        while t < phase_s:
            speed_mps = _phase_speed_mps(phase, t, prev_speed_mph)
            points.append(
                Trackpoint(
                    timestamp=start_time + timedelta(seconds=elapsed_s),
                    elapsed_s=elapsed_s,
                    distance_m=distance_m,
                    speed_mps=speed_mps,
                    hr_bpm=avg_hr,
                )
            )
            step = min(_TRACKPOINT_STEP_S, phase_s - t)
            if speed_mps:
                distance_m += speed_mps * step
            elapsed_s += step
            t += step
        if phase.speed_mph:
            prev_speed_mph = phase.speed_mph

    # Final closing sample at the exact end of the session.
    points.append(
        Trackpoint(
            timestamp=start_time + timedelta(seconds=elapsed_s),
            elapsed_s=elapsed_s,
            distance_m=distance_m,
            speed_mps=None,
            hr_bpm=avg_hr,
        )
    )

    # Summary metadata: the longest phase that has a reported speed is the "main" effort.
    main = max(
        (p for p in definition.phases if p.speed_mph),
        key=lambda p: p.duration_min or 0.0,
        default=None,
    )

    return Workout(
        id=start_time.strftime("%Y%m%dT%H%M%S"),
        source="manual_treadmill",
        source_file=source_file,
        sport="Running",
        start_time=start_time,
        duration_s=elapsed_s,
        distance_m=round(distance_m, 1),
        avg_hr=avg_hr,
        notes=text.strip(),
        treadmill_speed_mph=main.speed_mph if main else None,
        treadmill_incline_pct=main.incline_pct if main else None,
        trackpoints=points,
    )
