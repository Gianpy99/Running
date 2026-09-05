"""Smart-scale .xls reader (PRD §5.1, §17).

Reads INSMART-style exports where values carry unit suffixes (e.g. '87.1kg',
'22.9%'). Bioimpedance body-fat / muscle values are treated as noisy longitudinal
context, not clinical measurements (PRD §17).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..models import BodyMeasurement

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _num(value) -> float | None:
    if value is None:
        return None
    m = _NUM.search(str(value))
    return float(m.group()) if m else None


def _header_index(headers: list[str]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for i, h in enumerate(headers):
        idx[str(h).strip().lower()] = i
    return idx


def read_scale_xls(path: str | Path) -> list[BodyMeasurement]:
    """Parse a smart-scale .xls into chronologically sorted `BodyMeasurement`s."""
    import xlrd  # imported lazily so the core has no hard dependency at import time

    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    if sheet.nrows < 2:
        return []

    headers = [sheet.cell_value(0, c) for c in range(sheet.ncols)]
    idx = _header_index(headers)

    def col(*names: str) -> int | None:
        for n in names:
            if n in idx:
                return idx[n]
        return None

    c_time = col("time", "date")
    c_weight = col("weight")
    c_fat = col("body fat")
    c_muscle = col("muscle mass")
    c_water = col("body water")

    measurements: list[BodyMeasurement] = []
    for r in range(1, sheet.nrows):
        raw_time = sheet.cell_value(r, c_time) if c_time is not None else None
        if not raw_time:
            continue
        try:
            ts = datetime.fromisoformat(str(raw_time).strip())
        except ValueError:
            continue
        weight = _num(sheet.cell_value(r, c_weight)) if c_weight is not None else None
        if weight is None:
            continue
        measurements.append(
            BodyMeasurement(
                timestamp=ts,
                weight_kg=weight,
                body_fat_pct=_num(sheet.cell_value(r, c_fat)) if c_fat is not None else None,
                muscle_mass_kg=_num(sheet.cell_value(r, c_muscle)) if c_muscle is not None else None,
                water_pct=_num(sheet.cell_value(r, c_water)) if c_water is not None else None,
            )
        )

    measurements.sort(key=lambda m: m.timestamp)
    return measurements
