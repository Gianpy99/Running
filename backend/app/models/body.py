"""Body composition measurement from the smart scale (PRD §7, §17)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# The export names and units are also the dashboard's metric catalogue.
BODY_FIELDS = (
    ("Weight", "weight_kg", "kg"),
    ("BMI", "bmi", ""),
    ("Body fat", "body_fat_pct", "%"),
    ("Muscle mass", "muscle_mass_kg", "kg"),
    ("Body water", "water_pct", "%"),
    ("Visceral fat", "visceral_fat", ""),
    ("Bone mass", "bone_mass_kg", "kg"),
    ("BMR", "bmr_kcal", "kcal/day"),
    ("Protein", "protein_pct", "%"),
    ("Fat level", "fat_level", ""),
    ("Subcutaneous fat", "subcutaneous_fat_pct", "%"),
    ("Lean body mass", "lean_body_mass_kg", "kg"),
    ("Body Type", "body_type", ""),
    ("Standard Weight", "standard_weight_kg", "kg"),
    ("Heart Rate", "heart_rate_bpm", "bpm"),
    ("Body age", "body_age", "years"),
    ("Skeletal Muscle", "skeletal_muscle_pct", "%"),
    ("Muscle ratio", "muscle_ratio_pct", "%"),
)


class BodyMeasurement(BaseModel):
    """Smart-scale reading. Bioimpedance values are noisy estimates, not clinical (§17)."""

    model_config = ConfigDict(allow_inf_nan=False)

    timestamp: datetime
    weight_kg: float = Field(gt=0)
    body_fat_pct: float | None = None
    muscle_mass_kg: float | None = None
    water_pct: float | None = None
    bmi: float | None = None
    visceral_fat: float | None = None
    bone_mass_kg: float | None = None
    bmr_kcal: float | None = None
    protein_pct: float | None = None
    fat_level: float | None = None
    subcutaneous_fat_pct: float | None = None
    lean_body_mass_kg: float | None = None
    body_type: str | None = None
    standard_weight_kg: float | None = None
    heart_rate_bpm: float | None = None
    body_age: float | None = None
    skeletal_muscle_pct: float | None = None
    muscle_ratio_pct: float | None = None
    raw_values: dict[str, str] = Field(default_factory=dict)
    source: str = "insmart_xls"
