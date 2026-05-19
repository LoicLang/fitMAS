from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Mapping

from fitmas.decision import RequestedPlanChange

ReferenceKind = Literal["session", "date", "sport_window", "availability_window", "unknown"]
PlanningDecisionKind = Literal["commit", "pending_confirmation", "pending_choice", "block"]


@dataclass(frozen=True, slots=True)
class PlanChangeReference:
    kind: ReferenceKind
    raw: str | None
    session_id: int | None
    date: date | None
    sport_type: str | None = None
    availability: str | None = None
    scope: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None


@dataclass(frozen=True, slots=True)
class ResolvedPlanChange:
    requested_change: RequestedPlanChange
    source: PlanChangeReference
    target: PlanChangeReference
    warnings: tuple[str, ...]

    @property
    def kind(self) -> str:
        return self.requested_change.kind

    @property
    def reason(self) -> str:
        return self.requested_change.reason


@dataclass(frozen=True, slots=True)
class PlanningCandidateSet:
    candidates: tuple[Any, ...]
    backend_candidate_patches: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PlanningCommandResult:
    status: Literal["applied", "pending", "blocked", "skipped"]
    event_count: int
    pending_confirmation_id: int | None
    service_result: Any | None
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PlanningDecisionResult:
    kind: PlanningDecisionKind
    selected_candidate_id: str | None
    candidate_options: tuple[str, ...]
    reason: str
    policy_decision: Any | None
    selected_patch: Any | None
    evaluated_candidates: tuple[Any, ...]
    command_result: PlanningCommandResult | None
    pending_confirmation_id: int | None
