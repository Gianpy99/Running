"""Command-line entry point (PRD §23).

    running-coach import --raw <dir> --db <path> --report <path>
    running-coach analyse <file.tcx>
    running-coach replay <file.tcx>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import Athlete
from .persistence import open_store
from .services.pipeline import process_raw_directory, process_tcx_file
from .training.dsl import standard_treadmill_session
from .training.replay import replay_workout


def _cmd_import(args: argparse.Namespace) -> int:
    athlete = Athlete()
    report = process_raw_directory(args.raw, athlete)
    workouts = report.pop("_workouts")
    body = report.pop("_body_measurements")

    with open_store(args.db) as store:
        for workout, analysis in workouts:
            store.upsert_workout(workout, analysis)
        stored_body = store.upsert_body_measurements(body)

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")

    s = report["summary"]
    print(f"Imported {s['workouts_imported']} workouts "
          f"({s['total_distance_km']} km, {s['total_duration_min']} min), "
          f"{stored_body} body measurements.")
    print(f"Session breakdown: {s['session_breakdown']}")
    if report["quarantined"]:
        print(f"Quarantined {len(report['quarantined'])} file(s):")
        for q in report["quarantined"]:
            print(f"  - {q['file']}: {q['reason']}")
    print(f"Report written to {args.report}")
    print(f"Database: {args.db}")
    return 0


def _cmd_analyse(args: argparse.Namespace) -> int:
    _, analysis = process_tcx_file(args.file, Athlete())
    print(json.dumps(analysis, indent=2))
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    workout, _ = process_tcx_file(args.file, Athlete())
    events = replay_workout(standard_treadmill_session(), workout)
    for e in events:
        cues = "".join(c for c, on in (("V", e.vibrate), ("A", e.audio)) if on) or "-"
        print(f"[{e.at_s:7.1f}s] {e.kind.value:12s} {cues:3s} {e.message}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="running-coach", description="AI Running Coach — analytics core")
    sub = parser.add_subparsers(dest="command", required=True)

    p_imp = sub.add_parser("import", help="Reprocess raw TCX/XLS into the database + data-quality report")
    p_imp.add_argument("--raw", required=True, help="Directory containing raw .tcx/.xls files")
    p_imp.add_argument("--db", default="data/coach.db",
                       help="SQLite path or PostgreSQL DSN (postgresql://...); "
                            "falls back to DATABASE_URL/COACH_DB if unset")
    p_imp.add_argument("--report", default="data/processed/data_quality.json", help="Data-quality report path")
    p_imp.set_defaults(func=_cmd_import)

    p_an = sub.add_parser("analyse", help="Analyse a single TCX file and print JSON")
    p_an.add_argument("file")
    p_an.set_defaults(func=_cmd_analyse)

    p_rp = sub.add_parser("replay", help="Replay a TCX file through the live coach state machine")
    p_rp.add_argument("file")
    p_rp.set_defaults(func=_cmd_replay)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
