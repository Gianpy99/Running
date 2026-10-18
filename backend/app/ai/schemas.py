"""Editable coaching inputs and advisory-only structured output."""

from __future__ import annotations

from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CoachingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = "Europe/London"
    athlete_background: str = Field(default="", max_length=4000)
    goals: str = Field(default="", max_length=4000)
    training_constraints: str = Field(default="", max_length=4000)
    preferences: str = Field(default="", max_length=2000)
    history_notes: str = Field(default="", max_length=6000)
    planning_horizon: date | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone such as Europe/London.") from exc
        return value


class RaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    race_date: date | None = None
    distance_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    target_time_s: int | None = Field(default=None, gt=0)
    verified: bool = False
    priority: Literal["A", "B", "C"] = "B"
    status: Literal["planned", "completed", "cancelled"] = "planned"
    notes: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Race name cannot be blank.")
        return value.strip()


class WorkoutFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str = Field(default="", max_length=4000)
    perceived_exertion: int | None = Field(default=None, ge=1, le=10)


class CoachRequest(WorkoutFeedback):
    purpose: Literal["workout_feedback", "next_training"] = "workout_feedback"
    workout_id: str | None = Field(default=None, min_length=1, max_length=200)
    next_session_date: date | None = None
    available_minutes: int | None = Field(default=None, ge=5, le=360)
    setting: Literal["treadmill", "outdoor", "either"] = "either"
    sleep_hours: float | None = Field(default=None, ge=0, le=24, allow_inf_nan=False)
    subjective_energy: int | None = Field(default=None, ge=1, le=5)
    leg_fatigue: int | None = Field(default=None, ge=1, le=5)
    illness: bool | None = None
    concerning_pain: bool | None = None
    preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def feedback_requires_workout(self) -> CoachRequest:
        if self.purpose == "workout_feedback" and not self.workout_id:
            raise ValueError("Select a workout for feedback.")
        return self


class CoachStep(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    phase: Literal["warmup", "easy", "work", "recovery", "cooldown"]
    duration_min: float
    target: str


class NextSession(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    action: Literal["rest", "easy", "train", "ask"]
    date: date
    title: str
    rationale: str
    duration_min: float
    steps: list[CoachStep]

    @model_validator(mode="after")
    def coherent_duration(self) -> NextSession:
        if self.action in ("rest", "ask"):
            if self.duration_min != 0 or self.steps:
                raise ValueError("Rest or clarification must not prescribe exercise.")
        else:
            if not self.steps or self.duration_min <= 0:
                raise ValueError("Training requires timed steps.")
            if any(step.duration_min <= 0 for step in self.steps):
                raise ValueError("Step durations must be positive.")
            if abs(sum(step.duration_min for step in self.steps) - self.duration_min) > 0.1:
                raise ValueError("Step durations must add up to the session duration.")
            if self.action == "easy" and any(step.phase == "work" for step in self.steps):
                raise ValueError("An easy session cannot contain a work interval.")
        return self


class CoachOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    analysis: str
    observations: list[str]
    race_implications: list[str]
    next_session: NextSession | None
    uncertainties: list[str]
    questions: list[str]
