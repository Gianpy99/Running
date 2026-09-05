"""Ad-hoc inspection of the data-quality report (dev helper, not shipped logic)."""

import json
import sys

report = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data/processed/data_quality.json"))
for w in report["workouts"]:
    print(
        f"{w['start_time'][:10]} {w['session_type']:12s} {w['terrain']:14s} "
        f"{w['distance_m'] / 1000:5.2f}km {int(w['duration_s'] / 60):3d}min "
        f"hr={w['avg_hr']} suspect={w['hr_suspect_fraction']}"
    )
print("SUMMARY:", report["summary"])
