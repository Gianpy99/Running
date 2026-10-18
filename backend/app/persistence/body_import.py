"""Plan additive imports: timestamp identity, fill missing fields, never overwrite."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..models import BodyMeasurement
from ..models.body import BODY_FIELDS

_MISSING = {"", "--", "-", "n/a", "null"}


@dataclass
class BodyImportPlan:
    writes: list[BodyMeasurement] = field(default_factory=list)
    new: int = 0
    enriched: int = 0
    unchanged: int = 0
    conflicts: int = 0
    duplicate_rows: int = 0
    conflict_details: list[dict] = field(default_factory=list)

    def report(self) -> dict:
        return {
            key: value for key, value in vars(self).items() if key != "writes"
        }


def _merge(old: BodyMeasurement, incoming: BodyMeasurement) -> tuple[BodyMeasurement, list[str]]:
    fields = old.model_dump()
    conflicts = []
    for label, key, _ in BODY_FIELDS:
        previous, value = getattr(old, key), getattr(incoming, key)
        if value is None:
            continue
        if previous is None:
            fields[key] = value
        elif isinstance(previous, (int, float)) and isinstance(value, (int, float)):
            if not math.isclose(previous, value, rel_tol=0, abs_tol=0.000001):
                conflicts.append(label)
        elif previous != value:
            conflicts.append(label)
    raw = dict(old.raw_values)
    normalized = {key.lower(): key for key in raw}
    known = {label.lower() for label, _, _ in BODY_FIELDS} | {"time", "date"}
    for label, value in incoming.raw_values.items():
        old_key = normalized.get(label.lower(), label)
        previous = raw.get(old_key)
        if previous is None or previous.lower() in _MISSING:
            raw[old_key] = value
        elif (label.lower() not in known and value.lower() not in _MISSING
              and value != previous):
            conflicts.append(label)
    fields["raw_values"] = raw
    return BodyMeasurement.model_validate(fields), conflicts


def plan_body_import(
    existing: list[BodyMeasurement], incoming: list[BodyMeasurement],
) -> BodyImportPlan:
    result = BodyImportPlan()
    grouped: dict[str, BodyMeasurement] = {}
    conflicting_uploads: dict[str, list[str]] = {}
    for measurement in incoming:
        key = measurement.timestamp.isoformat()
        if key not in grouped:
            grouped[key] = measurement
        else:
            result.duplicate_rows += 1
            merged, conflicts = _merge(grouped[key], measurement)
            if conflicts:
                conflicting_uploads.setdefault(key, []).extend(conflicts)
            grouped[key] = merged
    stored = {measurement.timestamp.isoformat(): measurement for measurement in existing}
    for key, measurement in grouped.items():
        previous = stored.get(key)
        merged, conflicts = _merge(previous, measurement) if previous else (measurement, [])
        conflicts += conflicting_uploads.get(key, [])
        if conflicts:
            result.conflicts += 1
            if len(result.conflict_details) < 100:
                result.conflict_details.append({"timestamp": key, "fields": sorted(set(conflicts))})
        elif previous is None:
            result.new += 1
            result.writes.append(measurement)
        elif merged != previous:
            result.enriched += 1
            result.writes.append(merged)
        else:
            result.unchanged += 1
    return result
