"""Lossless scale imports, additive updates, migrations and mobile tracker contract."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import xlrd
from fastapi.testclient import TestClient

from app.api import create_app
from app.ingestion.scale_reader import MAX_SCALE_BYTES, parse_scale_xls, read_scale_xls
from app.models import BodyMeasurement
from app.models.body import BODY_FIELDS
from app.persistence import SqliteStore
from app.persistence.body_import import plan_body_import
from tests.conftest import REGRESSION_DIR

SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
HEADERS = ["time"] + [label for label, _, _ in BODY_FIELDS] + ["New future column"]
ROW = [
    "2026-10-13 08:14:45", "84.2kg", "26.6", "21.5%", "62.7kg", "56.6%",
    "9", "3.3kg", "1795", "17.8%", "26.6", "18.7%", "66.1kg",
    "Standard Muscle", "68.9kg", "--", "41", "50.6%", "74.5%", "Keep this text",
]


def fake_book(monkeypatch, rows=None, headers=None, *, date_cell=False, sheets=1):
    table = [headers if headers is not None else HEADERS] + (rows if rows is not None else [ROW])
    sheet = SimpleNamespace(
        nrows=len(table), ncols=len(table[0]), row_values=lambda index: table[index],
        cell_type=lambda row, col: xlrd.XL_CELL_DATE if date_cell and col == 0 else xlrd.XL_CELL_TEXT,
    )
    book = SimpleNamespace(
        nsheets=sheets, datemode=0, sheet_by_index=lambda index: sheet,
        release_resources=lambda: None,
    )
    monkeypatch.setattr(xlrd, "open_workbook", lambda **kwargs: book)
    return book


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "body.db")))


def measurement(timestamp="2026-10-13T08:14:45", **fields):
    return BodyMeasurement(timestamp=datetime.fromisoformat(timestamp), weight_kg=84.2, **fields)


def upload(client, data, preview=True, filename="history.xls"):
    return client.post(
        f"/body/import?preview={'true' if preview else 'false'}",
        files={"file": (filename, data, "application/vnd.ms-excel")},
    )


def test_original_regression_workbook_preserves_all_columns_and_cli_interface():
    parsed = parse_scale_xls((REGRESSION_DIR / "scale.xls").read_bytes())
    assert parsed.rows_read == 29
    assert len(parsed.measurements) == 29
    assert parsed.issue_count == 0
    assert len(parsed.columns) == 19
    assert len(parsed.measurements[-1].raw_values) == 19
    assert read_scale_xls(REGRESSION_DIR / "scale.xls") == parsed.measurements


def test_all_fields_unknown_columns_missing_hr_and_raw_cells_are_preserved(monkeypatch):
    fake_book(monkeypatch)
    parsed = parse_scale_xls(SIGNATURE)
    assert len(parsed.measurements) == 1
    result = parsed.measurements[0]
    assert result.weight_kg == 84.2
    assert result.bmi == 26.6
    assert result.bmr_kcal == 1795
    assert result.bone_mass_kg == 3.3
    assert result.skeletal_muscle_pct == 50.6
    assert result.muscle_ratio_pct == 74.5
    assert result.body_type == "Standard Muscle"
    assert result.heart_rate_bpm is None
    assert result.raw_values["Heart Rate"] == "--"
    assert result.raw_values["New future column"] == "Keep this text"
    assert parsed.issue_count == 0


def test_numeric_cells_excel_dates_and_decimal_commas_are_supported(monkeypatch):
    fake_book(monkeypatch, rows=[[46000.5, 80.2, "25,6%", 1750]],
              headers=["Date", "Weight", "Body fat", "BMR"], date_cell=True)
    parsed = parse_scale_xls(SIGNATURE)
    result = parsed.measurements[0]
    assert result.timestamp == xlrd.xldate_as_datetime(46000.5, 0)
    assert result.body_fat_pct == 25.6
    assert result.bmr_kcal == 1750
    assert parsed.issue_count == 0


def test_bad_optional_fields_warn_but_preserve_original_text(monkeypatch):
    fake_book(monkeypatch, rows=[["2026-10-13 08:00:00", "80kg", "not a number", "120%"]],
              headers=["Time", "Weight", "BMI", "Body water"])
    result = parse_scale_xls(SIGNATURE)
    assert len(result.measurements) == 1
    assert result.measurements[0].bmi is None
    assert result.measurements[0].water_pct is None
    assert result.measurements[0].raw_values["BMI"] == "not a number"
    assert result.issue_count == 2


def test_bad_rows_are_reported_not_silently_lost(monkeypatch):
    fake_book(monkeypatch, rows=[
        ["Bad date", "80kg"], ["2026-10-13", "--"], ["2026-10-13", "0kg"],
        ["2026-10-13", "180lb"], ["2026-10-13T08:00:00Z", "80kg"],
        ["2026-10-13", "80kg"], ["", ""],
    ], headers=["Time", "Weight"])
    result = parse_scale_xls(SIGNATURE)
    assert result.rows_read == 6
    assert result.rejected_rows == 5
    assert result.blank_rows == 1
    assert len(result.measurements) == 1
    assert result.issue_count >= 5


@pytest.mark.parametrize("headers", [
    ["Time", "BMI"], ["", "Weight"], ["Time", "Weight", "weight"],
])
def test_invalid_headers_are_rejected(monkeypatch, headers):
    fake_book(monkeypatch, rows=[[""] * len(headers)], headers=headers)
    with pytest.raises(ValueError):
        parse_scale_xls(SIGNATURE)


def test_multiple_sheets_oversize_and_invalid_formats_are_explicit(monkeypatch):
    fake_book(monkeypatch, sheets=2)
    with pytest.raises(ValueError, match="one scale-history"):
        parse_scale_xls(SIGNATURE)
    with pytest.raises(ValueError, match="5 MiB"):
        parse_scale_xls(b"x" * (MAX_SCALE_BYTES + 1))
    with pytest.raises(ValueError, match="original INSMART"):
        parse_scale_xls(b"PK renamed xlsx")


def test_corrupt_biff_file_has_a_clear_error():
    with pytest.raises(ValueError, match="could not be read"):
        parse_scale_xls(SIGNATURE + b"\0" * 512)


def test_invalid_rows_are_capped_and_never_create_successful_empty_import(client, monkeypatch):
    fake_book(monkeypatch, rows=[["Bad date", "80kg"]] * 110, headers=["Time", "Weight"])
    result = parse_scale_xls(SIGNATURE)
    assert result.issue_count == 110
    assert len(result.issues) == 100
    assert result.report()["issues_truncated"] is True
    response = upload(client, SIGNATURE, preview=False)
    assert response.status_code == 422
    assert response.json()["detail"]["rejected_rows"] == 110
    assert client.get("/body").json()["total"] == 0


def test_full_history_preview_import_and_repeat_have_exact_counts(client):
    content = (REGRESSION_DIR / "scale.xls").read_bytes()
    preview = upload(client, content)
    assert preview.status_code == 200
    assert preview.json()["new"] == 29
    assert preview.json()["stored_total"] == 0
    assert preview.json()["latest_in_file"]["bmi"] is not None
    assert client.get("/body").json()["total"] == 0
    imported = upload(client, content, preview=False).json()
    assert imported["new"] == 29
    assert imported["stored_total"] == 29
    repeated = upload(client, content, preview=False).json()
    assert repeated["new"] == 0
    assert repeated["enriched"] == 0
    assert repeated["unchanged"] == 29
    assert repeated["stored_total"] == 29


def test_older_gaps_new_rows_and_same_day_different_times_are_added(tmp_path):
    with SqliteStore(tmp_path / "history.db") as store:
        store.import_body_measurements([measurement()])
        incoming = [measurement(), measurement("2026-10-12T08:00:00"),
                    measurement("2026-10-13T19:00:00"), measurement("2026-10-14T08:00:00")]
        report = store.import_body_measurements(incoming)
        assert report["new"] == 3
        assert report["unchanged"] == 1
        assert len(store.list_body_measurements()) == 4


def test_existing_rows_gain_missing_fields_but_never_overwrite_conflicting_values(tmp_path):
    with SqliteStore(tmp_path / "history.db") as store:
        store.upsert_body_measurements([measurement()])
        detailed = measurement(bmi=26.6, bmr_kcal=1795, raw_values={"BMR": "1795"})
        report = store.import_body_measurements([detailed])
        assert report["enriched"] == 1
        changed = detailed.model_copy(update={"weight_kg": 83.9, "body_age": 42})
        conflict = store.import_body_measurements([changed])
        assert conflict["conflicts"] == 1
        assert conflict["new"] == conflict["enriched"] == 0
        stored = store.list_body_measurements()[0]
        assert stored.weight_kg == 84.2
        assert stored.body_age is None
        assert stored.bmr_kcal == 1795
        assert stored.raw_values == {"BMR": "1795"}


def test_duplicates_and_conflicts_within_the_same_file_are_not_last_row_wins():
    original = measurement()
    complete = measurement(bmi=26.6)
    merged = plan_body_import([], [original, complete])
    assert merged.new == 1
    assert merged.duplicate_rows == 1
    assert merged.writes[0].bmi == 26.6
    changed = original.model_copy(update={"weight_kg": 86.0})
    conflicting = plan_body_import([], [original, changed, complete])
    assert conflicting.conflicts == 1
    assert conflicting.duplicate_rows == 2
    assert conflicting.new == 0
    assert conflicting.writes == []


def test_raw_formatting_changes_are_unchanged_not_numeric_conflicts():
    original = measurement(raw_values={"Weight": "84.2kg", "Heart Rate": "--"})
    incoming = measurement(raw_values={"Weight": "84.20 kg", "Heart Rate": "--"})
    report = plan_body_import([original], [incoming])
    assert report.unchanged == 1
    assert report.conflicts == 0


def test_legacy_body_rows_migrate_and_gain_all_new_fields_without_duplicate(tmp_path):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE body_measurements (timestamp TEXT PRIMARY KEY, weight_kg REAL NOT NULL,
        body_fat_pct REAL, muscle_mass_kg REAL, water_pct REAL, source TEXT);
        INSERT INTO body_measurements VALUES ('2026-10-13T08:14:45',84.2,21.5,62.7,56.6,'insmart_xls');
    """)
    connection.close()
    for _ in range(2):
        with SqliteStore(path) as store:
            assert len(store.list_body_measurements()) == 1
    with SqliteStore(path) as store:
        report = store.import_body_measurements([
            measurement(body_fat_pct=21.5, muscle_mass_kg=62.7, water_pct=56.6,
                        bmi=26.6, body_type="Standard Muscle")
        ])
        assert report["enriched"] == 1
        assert len(store.list_body_measurements()) == 1
        assert store.list_body_measurements()[0].body_type == "Standard Muscle"


def test_simultaneous_reimports_do_not_duplicate_or_miscount(tmp_path):
    path = tmp_path / "concurrent.db"
    with SqliteStore(path):
        pass

    def perform_import(_):
        with SqliteStore(path) as store:
            return store.import_body_measurements([measurement()])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(perform_import, range(2)))
    assert sum(result["new"] for result in results) == 1
    assert sum(result["unchanged"] for result in results) == 1
    with SqliteStore(path) as store:
        assert len(store.list_body_measurements()) == 1


def test_preview_then_concurrent_import_recomputes_actual_changes(tmp_path):
    with SqliteStore(tmp_path / "race.db") as store:
        assert store.import_body_measurements([measurement()], preview=True)["new"] == 1
        store.import_body_measurements([measurement()])
        assert store.import_body_measurements([measurement()])["unchanged"] == 1


def test_failure_midway_rolls_back_the_entire_import(tmp_path, monkeypatch):
    with SqliteStore(tmp_path / "atomic.db") as store:
        original = store._exec
        writes = 0

        def fail_second_insert(sql, params=()):
            nonlocal writes
            if "INSERT INTO body_measurements" in sql:
                writes += 1
                if writes == 2:
                    raise sqlite3.OperationalError("simulated failure")
            return original(sql, params)

        monkeypatch.setattr(store, "_exec", fail_second_insert)
        with pytest.raises(sqlite3.OperationalError, match="simulated"):
            store.import_body_measurements([
                measurement(), measurement("2026-10-14T08:00:00"),
            ])
        assert store.list_body_measurements() == []


def test_body_api_pagination_metrics_and_rolling_contract(client, monkeypatch):
    now = datetime.now().replace(microsecond=0)
    rows = [
        [(now - timedelta(days=index)).isoformat(), f"{80 + index}kg", f"{20 + index}%"]
        for index in range(6)
    ]
    fake_book(monkeypatch, rows=rows, headers=["Time", "Weight", "Body fat"])
    assert upload(client, SIGNATURE, preview=False).status_code == 200
    result = client.get("/body?metric=body_fat_pct&limit=2&offset=2").json()
    assert result["total"] == 6
    assert result["filtered_total"] == 6
    assert len(result["measurements"]) == 2
    assert len(result["metrics"]) == 18
    assert result["series"][-1]["rolling"] == 22
    assert result["rolling_window"] == 5
    assert result["rolling_window_unit"] == "readings_with_a_value"
    assert client.get("/body?metric=heart_rate_bpm").json()["series"] == []
    assert client.get("/body?days=1").json()["filtered_total"] == 1
    assert client.get("/body?metric=not_a_metric").status_code == 422
    assert client.get("/body?offset=-1").status_code == 422
    assert client.get("/body?limit=101").status_code == 422
    assert client.get("/static/body.js").status_code == 200
    assert 'id="bodyTracker"' in client.get("/").text


def test_upload_invalid_formats_size_and_partial_warnings(client, monkeypatch):
    assert upload(client, b"bad").status_code == 422
    assert upload(client, SIGNATURE + b"\0" * 512).status_code == 422
    assert upload(client, b"bad", filename="file.xlsx").status_code == 422
    assert upload(client, b"x" * (MAX_SCALE_BYTES + 1)).status_code == 413
    fake_book(monkeypatch, headers=["Time", "Weight", "BMI"],
              rows=[["2026-10-13", "80kg", "nonsense"], ["wrong date", "82kg", "25"]])
    report = upload(client, SIGNATURE).json()
    assert report["valid_rows"] == 1
    assert report["rejected_rows"] == 1
    assert report["issue_count"] == 2
    assert report["new"] == 1


def test_tracker_import_does_not_add_body_data_to_ai_context(client):
    assert upload(client, (REGRESSION_DIR / "scale.xls").read_bytes(), preview=False).status_code == 200
    context = client.post("/ai/coaching/preview", json={"purpose": "next_training"}).json()["context"]
    assert "body_measurements" not in context
    assert "weight_kg" not in str(context)
    assert "bmr_kcal" not in str(context)
