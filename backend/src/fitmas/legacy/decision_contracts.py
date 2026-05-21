from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fitmas.decision.command_actions import (
    AvailabilityConstraintAction,
    ExecutionUpdateAction,
    HealthSignalAction,
    MemoryAction,
    PreferenceSignalAction,
)


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
