from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


CoachIntent = Literal[
    "close",
    "general_answer",
    "plan_lookup",
    "execution_report",
    "health_signal",
    "availability_signal",
    "plan_change",
    "pending_response",
    "clarification",
]

RequestedPlanChangeKind = Literal[
    "move",
    "swap",
    "lighten",
    "replace",
    "create",
    "constraint_window",
    "remove_optional",
    "unknown",
]


UserSignalType = Literal[
    "health",
    "availability",
    "preference",
    "execution",
    "readiness",
    "planning",
    "pending",
    "other",
]

PendingResolutionType = Literal[
    "accept_pending",
    "reject_pending",
    "modify_pending",
    "ignore",
    "needs_clarification",
]


def _validate_confidence(value: float) -> None:
    if value < 0.0 or value > 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class UserSignal:
    type: UserSignalType
    label: str
    status: str
    severity: str
    confidence: float
    evidence: str | None
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class PendingResolution:
    type: PendingResolutionType
    reason: str | None
    selected_candidate_id: str | None
    requested_changes: str | None
    question: str | None


@dataclass(frozen=True, slots=True)
class ClarificationNeed:
    reason: str
    missing_fields: tuple[str, ...]
    question_intent: str


@dataclass(frozen=True, slots=True)
class RequestedPlanChange:
    kind: RequestedPlanChangeKind
    source_ref: str | None
    target_ref: str | None
    desired_sport: str | None
    desired_duration_min: int | None
    desired_intensity: str | None
    reason: str
    risk_signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoachUnderstanding:
    intent: CoachIntent
    confidence: float
    user_summary: str
    extracted_signals: tuple[UserSignal, ...]
    requested_change: RequestedPlanChange | None
    pending_resolution: PendingResolution | None
    clarification_need: ClarificationNeed | None

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)
