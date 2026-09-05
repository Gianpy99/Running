"""Deterministic analytics engine (PRD §9).

Every metric here is reproducible from canonical trackpoints and exposes the thresholds
it used (PRD §4: "Every derived metric must be reproducible"). No AI is involved.
"""

from .quality import annotate_hr_quality, quality_summary
from .metrics import basic_metrics, hr_zone_distribution, splits
from .segmentation import segment_workout
from .terrain import elevation_profile, equivalent_flat_pace
from .efficiency import aerobic_efficiency, hr_drift
from .load import training_load
from .analysis import analyse_workout

__all__ = [
    "annotate_hr_quality",
    "quality_summary",
    "basic_metrics",
    "hr_zone_distribution",
    "splits",
    "segment_workout",
    "elevation_profile",
    "equivalent_flat_pace",
    "aerobic_efficiency",
    "hr_drift",
    "training_load",
    "analyse_workout",
]
