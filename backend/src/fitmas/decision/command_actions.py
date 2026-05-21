from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthSignalAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["record_health_signal"]
    health_signal: str
    body_area: str | None = None
    signal_kind: Literal["pain", "injury", "fatigue", "sleep", "illness", "tension", "other"] = "other"
    severity: Literal["mild", "moderate", "severe", "unknown"] = "unknown"
    status: Literal["new", "ongoing", "improving", "worsening", "resolved", "unknown"] = "unknown"
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence: str | None = None


class AvailabilityConstraintAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["record_availability"]
    window_text: str
    availability: Literal["unavailable", "limited", "available", "unknown"]
    sport_type: str | None = None
    scope: str | None = None
    starts_on: str | None = None
    ends_on: str | None = None
    recurrence: str | None = None
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence: str | None = None


class PreferenceSignalAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["record_preference"]
    preference: str
    polarity: Literal["prefer", "avoid", "like", "dislike", "neutral", "unknown"]
    scope: str | None = None
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence: str | None = None


class ExecutionUpdateAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["record_execution_update"]
    target_ref: str
    target_session_id: int | None = None
    status: Literal["completed", "not_completed", "partially_completed", "unknown"]
    completed: bool | None = None
    sport_type: str | None = None
    duration_min: int | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence: str | None = None


MemoryAction = Annotated[
    HealthSignalAction | AvailabilityConstraintAction | PreferenceSignalAction,
    Field(discriminator="type"),
]


__all__ = [
    "AvailabilityConstraintAction",
    "ExecutionUpdateAction",
    "HealthSignalAction",
    "MemoryAction",
    "PreferenceSignalAction",
]
