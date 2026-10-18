"""INSMART BIFF .xls exports, retaining every column and reporting bad rows."""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import xlrd
from xlrd.compdoc import CompDocError

from ..models import BodyMeasurement
from ..models.body import BODY_FIELDS

MAX_SCALE_BYTES = 5 * 1024 * 1024
MAX_SCALE_ROWS = 20000
_MISSING = {"", "--", "-", "n/a", "null"}
_NUMBER = re.compile(r"([+-]?\d+(?:[.,]\d+)?)\s*([a-zA-Z%/]*)")


@dataclass
class ScaleImport:
    measurements: list[BodyMeasurement] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows_read: int = 0
    blank_rows: int = 0
    rejected_rows: int = 0
    issue_count: int = 0
    issues: list[dict] = field(default_factory=list)

    def issue(self, row: int, column: str, message: str) -> None:
        self.issue_count += 1
        if len(self.issues) < 100:
            self.issues.append({"row": row, "column": column, "message": message})

    def report(self) -> dict:
        return {
            "columns": self.columns, "rows_read": self.rows_read,
            "valid_rows": len(self.measurements), "blank_rows": self.blank_rows,
            "rejected_rows": self.rejected_rows, "issue_count": self.issue_count,
            "issues": self.issues, "issues_truncated": self.issue_count > len(self.issues),
        }


def _number(value: str, unit: str) -> float | None:
    text = value.strip()
    if text.lower() in _MISSING:
        return None
    match = _NUMBER.fullmatch(text)
    if not match:
        raise ValueError("Expected a number with the export's original units.")
    suffix = match[2].lower()
    accepted = {"", unit.lower()}
    if unit == "kcal/day":
        accepted.add("kcal")
    if suffix not in accepted:
        raise ValueError(f"Unsupported unit; expected {unit or 'a unitless number'}.")
    result = float(match[1].replace(",", "."))
    if not math.isfinite(result) or result < 0 or (unit == "%" and result > 100):
        raise ValueError("Value is outside the supported numeric range.")
    return result


def parse_scale_xls(content: bytes) -> ScaleImport:
    """Parse without writing. Timestamps retain the export's local wall-clock time."""
    if len(content) > MAX_SCALE_BYTES:
        raise ValueError("Scale exports must be no larger than 5 MiB.")
    if not content.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        raise ValueError("Upload the original INSMART .xls export, not an .xlsx or renamed file.")
    try:
        book = xlrd.open_workbook(file_contents=content)
    except (xlrd.XLRDError, CompDocError, ValueError, IndexError, struct.error) as exc:
        raise ValueError("The .xls workbook could not be read. Export it again from INSMART.") from exc
    try:
        if book.nsheets != 1:
            raise ValueError("Expected one scale-history sheet. Upload the original INSMART export.")
        sheet = book.sheet_by_index(0)
        if sheet.nrows < 2:
            raise ValueError("The workbook contains no measurement rows.")
        if sheet.nrows - 1 > MAX_SCALE_ROWS or sheet.ncols > 100:
            raise ValueError("Scale exports support at most 20,000 rows and 100 columns.")
        headers = [str(value).strip() for value in sheet.row_values(0)]
        normalized = [value.lower() for value in headers]
        if any(not value for value in headers) or len(set(normalized)) != len(normalized):
            raise ValueError("Every export column needs a unique, nonempty header.")
        time_name = "time" if "time" in normalized else "date"
        if time_name not in normalized or "weight" not in normalized:
            raise ValueError("The export must contain Time (or Date) and Weight columns.")
        time_index = normalized.index(time_name)
        mapping = {label.lower(): (key, unit) for label, key, unit in BODY_FIELDS}
        result = ScaleImport(columns=headers)
        for row_index in range(1, sheet.nrows):
            cells = sheet.row_values(row_index)
            if all(value == "" for value in cells):
                result.blank_rows += 1
                continue
            result.rows_read += 1
            values = {
                header: str(value).strip() for header, value in zip(headers, cells)
            }
            try:
                if sheet.cell_type(row_index, time_index) == xlrd.XL_CELL_DATE:
                    timestamp = xlrd.xldate_as_datetime(cells[time_index], book.datemode)
                else:
                    timestamp = datetime.fromisoformat(str(cells[time_index]).strip())
                if timestamp.tzinfo is not None:
                    raise ValueError("Expected a local scale timestamp without a timezone suffix.")
            except (ValueError, TypeError, OverflowError) as exc:
                result.issue(row_index + 1, headers[time_index], str(exc))
                result.rejected_rows += 1
                continue
            fields: dict = {"timestamp": timestamp, "raw_values": values}
            for header, text in values.items():
                if header.lower() not in mapping:
                    continue
                key, unit = mapping[header.lower()]
                try:
                    fields[key] = (
                        (None if text.lower() in _MISSING else text)
                        if key == "body_type" else _number(text, unit)
                    )
                except ValueError as exc:
                    result.issue(row_index + 1, header, str(exc))
                    fields[key] = None
            if not fields.get("weight_kg") or fields["weight_kg"] <= 0:
                result.issue(row_index + 1, "Weight", "A positive weight in kg is required; row skipped.")
                result.rejected_rows += 1
                continue
            result.measurements.append(BodyMeasurement.model_validate(fields))
        result.measurements.sort(key=lambda measurement: measurement.timestamp)
        return result
    finally:
        book.release_resources()


def read_scale_xls(path: str | Path) -> list[BodyMeasurement]:
    """CLI adapter: quarantine an imperfect file rather than silently dropping values."""
    result = parse_scale_xls(Path(path).read_bytes())
    if result.issue_count:
        raise ValueError(
            f"Scale export has {result.issue_count} data issue(s). "
            "Use the dashboard upload to review valid rows and all warnings."
        )
    return result.measurements
