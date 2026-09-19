"""Basic metrics: distance, duration, moving time, distributions, splits, zones (§9.1)."""

from __future__ import annotations

from ..models import Athlete, Workout

WALKING_SPEED_THRESHOLD_MPS = 1.8  # ~9:15/km; below this we treat motion as walking
MOVING_SPEED_THRESHOLD_MPS = 0.5  # below this the athlete is considered paused


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def basic_metrics(workout: Workout, window: tuple[float, float] | None = None) -> dict:
    """Distance/duration/moving time plus pace, HR and elevation distributions.

    `window`, if given, is an (start_s, end_s) elapsed-time range (see
    `segmentation.main_set_window`); only trackpoints inside it are considered, so callers
    can get stats for just the "real" training with warmup/cooldown trimmed off.
    """
    pts = workout.trackpoints
    if window is not None:
        lo, hi = window
        pts = [p for p in pts if lo <= p.elapsed_s <= hi]

    moving_s = 0.0
    paused_s = 0.0
    walking_s = 0.0
    speeds: list[float] = []
    hrs: list[int] = []
    distance_m = 0.0

    for i in range(1, len(pts)):
        prev, cur = pts[i - 1], pts[i]
        dt = (cur.timestamp - prev.timestamp).total_seconds()
        if dt <= 0:
            continue
        speed = cur.speed_mps or 0.0
        if speed < MOVING_SPEED_THRESHOLD_MPS:
            paused_s += dt
        else:
            moving_s += dt
            if speed < WALKING_SPEED_THRESHOLD_MPS:
                walking_s += dt
        if speed > 0:
            speeds.append(speed)
        if cur.hr_bpm is not None:
            hrs.append(cur.hr_bpm)
        distance_m += (cur.distance_m or 0.0) - (prev.distance_m or 0.0)

    duration_s = pts[-1].elapsed_s - pts[0].elapsed_s if len(pts) > 1 else 0.0
    if window is None:
        # Whole-session totals are authoritative (lap-derived where available).
        distance_m = workout.distance_m
        duration_s = workout.duration_s

    avg_speed = sum(speeds) / len(speeds) if speeds else 0.0
    avg_pace = 1000.0 / avg_speed if avg_speed > 0 else None

    # Fallback for sessions with no per-point speed signal (e.g. treadmill TCX without
    # GPS/distance streams): derive averages and moving time from totals.
    no_speed_signal = not speeds
    if no_speed_signal and distance_m > 0 and duration_s > 0:
        avg_speed = distance_m / duration_s
        avg_pace = 1000.0 / avg_speed if avg_speed > 0 else None
        moving_s = duration_s
        paused_s = 0.0
        walking_s = 0.0

    return {
        "distance_m": round(distance_m, 1),
        "duration_s": round(duration_s, 1),
        "moving_s": round(moving_s, 1),
        "paused_s": round(paused_s, 1),
        "walking_s": round(walking_s, 1),
        "avg_speed_mps": round(avg_speed, 3),
        "avg_pace_s_per_km": round(avg_pace, 1) if avg_pace else None,
        "pace_p50_s_per_km": _pace(_percentile(speeds, 0.5)),
        "pace_p90_s_per_km": _pace(_percentile(speeds, 0.9)),
        "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None,
        "max_hr": max(hrs) if hrs else None,
        "min_hr": min(hrs) if hrs else None,
        "thresholds": {
            "walking_speed_mps": WALKING_SPEED_THRESHOLD_MPS,
            "moving_speed_mps": MOVING_SPEED_THRESHOLD_MPS,
        },
    }


def _pace(speed: float | None) -> float | None:
    return round(1000.0 / speed, 1) if speed and speed > 0 else None


def hr_zone_distribution(workout: Workout, athlete: Athlete) -> dict:
    """Seconds spent in each of five HR zones using the athlete's zone bounds (§9.1)."""
    bounds = athlete.zone_bounds()  # 5 lower bounds
    seconds = [0.0] * (len(bounds) + 1)
    pts = workout.trackpoints
    for i in range(1, len(pts)):
        hr = pts[i].hr_bpm
        if hr is None:
            continue
        dt = (pts[i].timestamp - pts[i - 1].timestamp).total_seconds()
        if dt <= 0:
            continue
        zone = 0
        for b in bounds:
            if hr >= b:
                zone += 1
        seconds[zone] += dt
    return {
        "zone_bounds_bpm": bounds,
        "seconds_per_zone": [round(s, 1) for s in seconds],
    }


def splits(workout: Workout, split_m: float = 1000.0) -> list[dict]:
    """Per-kilometre splits with duration and average HR (§9.1)."""
    pts = workout.trackpoints
    if not pts:
        return []
    result: list[dict] = []
    next_mark = split_m
    seg_start = pts[0]
    hr_sum = 0
    hr_n = 0
    for p in pts:
        if p.hr_bpm is not None:
            hr_sum += p.hr_bpm
            hr_n += 1
        if (p.distance_m or 0.0) >= next_mark:
            dur = (p.timestamp - seg_start.timestamp).total_seconds()
            result.append(
                {
                    "split_km": round(next_mark / 1000.0, 1),
                    "duration_s": round(dur, 1),
                    "pace_s_per_km": round(dur / (split_m / 1000.0), 1),
                    "avg_hr": round(hr_sum / hr_n) if hr_n else None,
                }
            )
            seg_start = p
            hr_sum, hr_n = 0, 0
            next_mark += split_m
    return result
