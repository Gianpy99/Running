"""TCX parser → canonical `Workout` with `Trackpoint`s (PRD §5.1, §7).

Namespace-agnostic: Garmin TCX uses default + activity-extension namespaces. We match on
local tag names so the parser tolerates namespace variation across exporters.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from ..models import Trackpoint, Workout
from ..models.enums import CompletionStatus
from .geo import haversine_m


def _local(tag: str) -> str:
    """Strip an XML namespace from a tag: '{ns}Trackpoint' -> 'Trackpoint'."""
    return tag.rsplit("}", 1)[-1]


def _find(el: ET.Element, name: str) -> ET.Element | None:
    for child in el.iter():
        if _local(child.tag) == name:
            return child
    return None


def _find_direct(el: ET.Element, name: str) -> ET.Element | None:
    for child in el:
        if _local(child.tag) == name:
            return child
    return None


def _text_of(el: ET.Element, name: str) -> str | None:
    node = _find(el, name)
    return node.text.strip() if node is not None and node.text else None


def _parse_time(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, normalising a trailing 'Z' to +00:00."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iter_trackpoints(activity: ET.Element):
    for node in activity.iter():
        if _local(node.tag) == "Trackpoint":
            yield node


def parse_tcx(content: str, source_file: str | None = None) -> Workout:
    """Parse TCX XML text into a canonical `Workout`.

    Speed is taken from a TPX extension when present, otherwise derived from
    distance/time deltas. GPS distance is used as a fallback when the file omits
    cumulative `DistanceMeters`.
    """
    root = ET.fromstring(content)
    activity = _find(root, "Activity")
    if activity is None:
        raise ValueError("No <Activity> element found in TCX")

    sport = activity.get("Sport", "Running")
    start_id = _text_of(activity, "Id")
    laps = [n for n in activity.iter() if _local(n.tag) == "Lap"]

    trigger_methods = {(_text_of(lap, "TriggerMethod") or "").lower() for lap in laps}
    lap_total_time = sum(float(_text_of(lap, "TotalTimeSeconds") or 0.0) for lap in laps)
    lap_total_distance = sum(
        float(_text_of(lap, "DistanceMeters") or 0.0) for lap in laps
    )

    points: list[Trackpoint] = []
    prev: Trackpoint | None = None
    cumulative_gps_m = 0.0

    for tp in _iter_trackpoints(activity):
        time_str = _text_of(tp, "Time")
        if not time_str:
            continue
        ts = _parse_time(time_str)

        lat = lon = alt = dist = None
        pos = _find_direct(tp, "Position")
        if pos is not None:
            lat_s = _text_of(pos, "LatitudeDegrees")
            lon_s = _text_of(pos, "LongitudeDegrees")
            lat = float(lat_s) if lat_s else None
            lon = float(lon_s) if lon_s else None
        alt_s = _text_of(tp, "AltitudeMeters")
        alt = float(alt_s) if alt_s else None
        dist_s = _text_of(tp, "DistanceMeters")
        dist = float(dist_s) if dist_s else None

        hr = None
        hr_node = _find_direct(tp, "HeartRateBpm")
        if hr_node is not None:
            hr_val = _text_of(hr_node, "Value")
            hr = int(round(float(hr_val))) if hr_val else None

        cad_s = _text_of(tp, "Cadence")
        cadence = int(round(float(cad_s))) if cad_s else None

        speed = None
        speed_node = _find(tp, "Speed")
        if speed_node is not None and speed_node.text:
            speed = float(speed_node.text)

        point = Trackpoint(
            timestamp=ts,
            distance_m=dist,
            latitude=lat,
            longitude=lon,
            altitude_m=alt,
            speed_mps=speed,
            hr_bpm=hr,
            cadence_spm=cadence,
        )

        if prev is not None:
            dt = (ts - prev.timestamp).total_seconds()
            point.elapsed_s = prev.elapsed_s + max(dt, 0.0)
            if lat is not None and lon is not None and prev.latitude is not None:
                cumulative_gps_m += haversine_m(
                    prev.latitude, prev.longitude, lat, lon
                )
            if point.distance_m is None:
                point.distance_m = cumulative_gps_m
            if speed is None and dt > 0 and point.distance_m is not None:
                d_dist = point.distance_m - (prev.distance_m or 0.0)
                point.speed_mps = max(d_dist / dt, 0.0)
        else:
            point.elapsed_s = 0.0
            if point.distance_m is None:
                point.distance_m = 0.0

        points.append(point)
        prev = point

    if not points:
        raise ValueError("TCX contained no usable trackpoints")

    start_time = _parse_time(start_id) if start_id else points[0].timestamp
    duration_s = lap_total_time or points[-1].elapsed_s
    distance_m = lap_total_distance or (points[-1].distance_m or 0.0)

    completion = CompletionStatus.UNKNOWN
    if "manual" in trigger_methods:
        completion = CompletionStatus.COMPLETE

    workout_id = start_time.strftime("%Y%m%dT%H%M%S")
    return Workout(
        id=workout_id,
        source="tcx",
        source_file=source_file,
        sport=sport,
        start_time=start_time,
        duration_s=duration_s,
        distance_m=distance_m,
        completion=completion,
        trackpoints=points,
    )


def parse_tcx_file(path: str | Path) -> Workout:
    p = Path(path)
    return parse_tcx(p.read_text(encoding="utf-8"), source_file=p.name)
