"""Scale-history upload and body-tracker API; these data are not sent to AI."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from ..ingestion.scale_reader import MAX_SCALE_BYTES, parse_scale_xls
from ..models.body import BODY_FIELDS
from ..persistence.store import _BaseStore


def register_body_routes(app: FastAPI, store: Callable[[], _BaseStore]) -> None:
    @app.post("/body/import")
    async def import_scale(
        file: UploadFile = File(...), preview: bool = Query(True),
    ) -> dict:
        if not file.filename or not file.filename.lower().endswith(".xls"):
            raise HTTPException(422, "Choose the original INSMART .xls export.")
        content = await file.read(MAX_SCALE_BYTES + 1)
        if len(content) > MAX_SCALE_BYTES:
            raise HTTPException(413, "Scale exports must be no larger than 5 MiB.")
        try:
            parsed = parse_scale_xls(content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not parsed.measurements:
            raise HTTPException(422, {
                "message": "No valid measurements were found. Nothing was imported.",
                **parsed.report(),
            })
        with store() as s:
            changes = s.import_body_measurements(parsed.measurements, preview=preview)
            total = len(s.list_body_measurements())
        return {
            "preview": preview, **parsed.report(), **changes,
            "stored_total": total,
            "latest_in_file": (
                parsed.measurements[-1].model_dump(mode="json") if parsed.measurements else None
            ),
            "sample": [
                measurement.model_dump(mode="json") for measurement in parsed.measurements[-20:][::-1]
            ],
            "sample_limit": 20,
        }

    @app.get("/body")
    def body_tracker(
        metric: str = "weight_kg", days: int | None = Query(None, ge=1, le=36500),
        offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
    ) -> dict:
        catalogue = [
            {"label": label, "field": key, "unit": unit, "numeric": key != "body_type"}
            for label, key, unit in BODY_FIELDS
        ]
        numeric = {item["field"] for item in catalogue if item["numeric"]}
        if metric not in numeric:
            raise HTTPException(422, "Choose a supported numeric body metric.")
        with store() as s:
            measurements = s.list_body_measurements()
            profile = s.get_coaching_profile() or {}
        today = datetime.now(ZoneInfo(profile.get("timezone", "Europe/London"))).date()
        cutoff = today - timedelta(days=days - 1) if days is not None else None
        filtered = [
            measurement for measurement in measurements
            if (cutoff is None or measurement.timestamp.date() >= cutoff)
            and measurement.timestamp.date() <= today
        ]
        points = []
        values: list[float] = []
        for measurement in filtered:
            value = getattr(measurement, metric)
            if value is not None:
                values.append(value)
                points.append({
                    "timestamp": measurement.timestamp.isoformat(), "value": value,
                    "rolling": round(sum(values[-5:]) / min(5, len(values)), 3),
                })
        latest = measurements[-1] if measurements else None
        return {
            "total": len(measurements), "filtered_total": len(filtered),
            "offset": offset, "limit": limit, "metric": metric, "days": days,
            "metrics": catalogue,
            "latest": latest.model_dump(mode="json") if latest else None,
            "first_date": measurements[0].timestamp.isoformat() if measurements else None,
            "last_date": latest.timestamp.isoformat() if latest else None,
            "future_readings": sum(measurement.timestamp.date() > today for measurement in measurements),
            "series": points[-1000:],
            "series_total": len(points), "series_limit": 1000,
            "rolling_window": 5, "rolling_window_unit": "readings_with_a_value",
            "measurements": [
                measurement.model_dump(mode="json")
                for measurement in filtered[::-1][offset:offset + limit]
            ],
        }
