"""Time-series segmentation (PRD §9.2).

Detects walking, pauses, accelerations and workout segments, preserving the thresholds
used and a confidence estimate per segment (PRD §9.2: "Preserve uncertainty and
thresholds used").
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..models import Workout
from ..models.enums import SegmentType

PAUSE_SPEED_MPS = 0.5
WALK_SPEED_MPS = 1.8
STEADY_SPEED_MPS = 2.3  # ~7:15/km lower edge of steady aerobic running
MODERATE_SPEED_MPS = 3.0
FAST_SPEED_MPS = 3.6
MIN_SEGMENT_S = 20.0  # merge shorter runs into neighbours to avoid fragmentation


@dataclass
class Segment:
    type: str
    start_s: float
    end_s: float
    duration_s: float
    avg_speed_mps: float | None
    avg_hr: float | None
    confidence: float


def _classify(speed: float, elapsed: float, total: float) -> SegmentType:
    if speed < PAUSE_SPEED_MPS:
        return SegmentType.PAUSED
    if speed < WALK_SPEED_MPS:
        return SegmentType.WALKING
    if speed < STEADY_SPEED_MPS:
        # Slow running early = warmup, late = cooldown, otherwise recovery.
        if elapsed < 0.2 * total:
            return SegmentType.WARMUP
        if elapsed > 0.85 * total:
            return SegmentType.COOLDOWN
        return SegmentType.RECOVERY
    if speed < MODERATE_SPEED_MPS:
        return SegmentType.STEADY_AEROBIC
    if speed < FAST_SPEED_MPS:
        return SegmentType.MODERATE
    return SegmentType.FAST


def segment_workout(workout: Workout) -> dict:
    """Return ordered segments with the thresholds used (reproducible, §9.2)."""
    pts = workout.trackpoints
    total = workout.duration_s or (pts[-1].elapsed_s if pts else 0.0)
    raw: list[tuple[SegmentType, float, float, float | None, float | None]] = []

    for i in range(1, len(pts)):
        prev, cur = pts[i - 1], pts[i]
        dt = (cur.timestamp - prev.timestamp).total_seconds()
        if dt <= 0:
            continue
        speed = cur.speed_mps or 0.0
        label = _classify(speed, cur.elapsed_s, total)
        raw.append((label, prev.elapsed_s, cur.elapsed_s, speed, cur.hr_bpm))

    segments = _coalesce(raw)
    return {
        "segments": [asdict(s) for s in segments],
        "thresholds": {
            "pause_speed_mps": PAUSE_SPEED_MPS,
            "walk_speed_mps": WALK_SPEED_MPS,
            "steady_speed_mps": STEADY_SPEED_MPS,
            "moderate_speed_mps": MODERATE_SPEED_MPS,
            "fast_speed_mps": FAST_SPEED_MPS,
            "min_segment_s": MIN_SEGMENT_S,
        },
    }


def _coalesce(raw) -> list[Segment]:
    if not raw:
        return []
    segments: list[Segment] = []
    cur_label = raw[0][0]
    start = raw[0][1]
    speeds: list[float] = []
    hrs: list[float] = []
    end = raw[0][2]

    def flush(label, s0, s1, sp, hr) -> Segment:
        dur = max(s1 - s0, 0.0)
        avg_sp = sum(sp) / len(sp) if sp else None
        avg_hr = sum(hr) / len(hr) if hr else None
        # Confidence falls near class boundaries; short segments are less certain.
        conf = 0.9 if dur >= 3 * MIN_SEGMENT_S else 0.6
        return Segment(label.value, round(s0, 1), round(s1, 1), round(dur, 1),
                       round(avg_sp, 3) if avg_sp else None,
                       round(avg_hr, 1) if avg_hr else None, conf)

    for label, s0, s1, sp, hr in raw:
        if label == cur_label:
            end = s1
            if sp is not None:
                speeds.append(sp)
            if hr is not None:
                hrs.append(hr)
        else:
            seg = flush(cur_label, start, end, speeds, hrs)
            if seg.duration_s >= MIN_SEGMENT_S or not segments:
                segments.append(seg)
            else:
                # Absorb tiny segment into the previous one.
                prev = segments[-1]
                prev.end_s = seg.end_s
                prev.duration_s = round(prev.end_s - prev.start_s, 1)
            cur_label = label
            start = s0
            speeds = [sp] if sp is not None else []
            hrs = [hr] if hr is not None else []
            end = s1
    segments.append(flush(cur_label, start, end, speeds, hrs))
    return segments
