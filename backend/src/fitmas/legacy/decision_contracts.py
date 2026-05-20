from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MutationDecision(BaseModel):
    mutation_type: str
    target_session_id: int | None = None
    second_session_id: int | None = None
    target_date: str | None = None
    from_day: str | None = None
    to_day: str | None = None
    new_title: str | None = None
    new_goal: str | None = None
    new_sport_type: str | None = None
    new_session_type: str | None = None
    new_duration_min: int | None = None
    new_intensity: str | None = None
    new_description: str | None = None
    rationale: str
    fitmas_message: str


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


class AcceptPendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["accept_pending"]
    reason: str | None = None
    selected_candidate_id: str | None = None


class RejectPendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["reject_pending"]
    reason: str | None = None


class ModifyPendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["modify_pending"]
    requested_changes: str
    reason: str | None = None


class IgnorePendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["ignore"]
    reason: str | None = None


class NeedsClarificationPendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["needs_clarification"]
    reason: str
    question: str


MemoryAction = Annotated[
    HealthSignalAction | AvailabilityConstraintAction | PreferenceSignalAction,
    Field(discriminator="type"),
]
PendingResolution = Annotated[
    AcceptPendingResolution
    | RejectPendingResolution
    | ModifyPendingResolution
    | IgnorePendingResolution
    | NeedsClarificationPendingResolution,
    Field(discriminator="type"),
]


class CoachDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    response_type: Literal["reply", "no_change", "mutation_decision", "plan_patch", "requires_confirmation"]
    rationale: str
    fitmas_message: str
    mutation_decision: MutationDecision | None = None
    plan_patch: Any | None = None
    confirmation_reason: str | None = None
    memory_actions: tuple[MemoryAction, ...] = ()
    execution_actions: tuple[ExecutionUpdateAction, ...] = ()
    pending_resolution: PendingResolution | None = None


__all__ = [
    "AcceptPendingResolution",
    "AvailabilityConstraintAction",
    "CoachDecision",
    "ExecutionUpdateAction",
    "HealthSignalAction",
    "IgnorePendingResolution",
    "MemoryAction",
    "ModifyPendingResolution",
    "MutationDecision",
    "NeedsClarificationPendingResolution",
    "PendingResolution",
    "PreferenceSignalAction",
    "RejectPendingResolution",
]
