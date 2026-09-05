"""HR signal-quality detection (PRD §9.3).

Detects implausible jumps, flatlines, missing data and abrupt recovery. Flags annotate
trackpoints for down-weighting in physiological analysis; raw values are never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Trackpoint, Workout
from ..models.enums import QualityFlag

# Thresholds are explicit so results are reproducible and auditable.
MAX_HR_DELTA_BPM_PER_S = 8  # sustained >8 bpm/s is implausible for adjacent samples
FLATLINE_MIN_SAMPLES = 15  # identical HR for this many samples = flatline
PLAUSIBLE_HR_RANGE = (30, 220)


@dataclass
class HRQualityResult:
    flagged_samples: int
    total_samples: int
    thresholds: dict

    @property
    def suspect_fraction(self) -> float:
        return self.flagged_samples / self.total_samples if self.total_samples else 0.0


def annotate_hr_quality(workout: Workout) -> HRQualityResult:
    """Annotate trackpoints in-place with HR quality flags and return a summary."""
    pts = workout.trackpoints
    flagged = 0

    run_value: int | None = None
    run_len = 0

    for i, p in enumerate(pts):
        flags: list[QualityFlag] = []
        hr = p.hr_bpm

        if hr is None or not (PLAUSIBLE_HR_RANGE[0] <= hr <= PLAUSIBLE_HR_RANGE[1]):
            flags.append(QualityFlag.HR_MISSING)
        else:
            if i > 0:
                prev = pts[i - 1]
                dt = max((p.timestamp - prev.timestamp).total_seconds(), 1.0)
                if prev.hr_bpm is not None:
                    rate = abs(hr - prev.hr_bpm) / dt
                    if rate > MAX_HR_DELTA_BPM_PER_S:
                        # A large upward jump after missing/low data reads as recovery.
                        if prev.hr_bpm < hr and QualityFlag.HR_MISSING in prev.quality:
                            flags.append(QualityFlag.HR_ABRUPT_RECOVERY)
                        else:
                            flags.append(QualityFlag.HR_IMPLAUSIBLE_JUMP)

            # Flatline tracking.
            if hr == run_value:
                run_len += 1
            else:
                run_value, run_len = hr, 1
            if run_len >= FLATLINE_MIN_SAMPLES:
                flags.append(QualityFlag.HR_FLATLINE)

        p.quality = flags or [QualityFlag.OK]
        if flags:
            flagged += 1

    return HRQualityResult(
        flagged_samples=flagged,
        total_samples=len(pts),
        thresholds={
            "max_hr_delta_bpm_per_s": MAX_HR_DELTA_BPM_PER_S,
            "flatline_min_samples": FLATLINE_MIN_SAMPLES,
            "plausible_hr_range": list(PLAUSIBLE_HR_RANGE),
        },
    )


def quality_summary(workout: Workout) -> dict:
    """Summary of quality flags across a workout for the data-quality report (§13)."""
    counts: dict[str, int] = {}
    for p in workout.trackpoints:
        for f in p.quality:
            counts[f.value] = counts.get(f.value, 0) + 1
    total = len(workout.trackpoints)
    hr_present = sum(1 for p in workout.trackpoints if p.hr_bpm is not None)
    gps_present = sum(1 for p in workout.trackpoints if p.latitude is not None)
    return {
        "total_trackpoints": total,
        "flag_counts": counts,
        "hr_coverage": round(hr_present / total, 3) if total else 0.0,
        "gps_coverage": round(gps_present / total, 3) if total else 0.0,
    }
