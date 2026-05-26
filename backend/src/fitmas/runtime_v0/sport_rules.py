from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from fitmas.runtime_v0.proposals import PlanPatchDraft, PlanPatchOperation
from fitmas.runtime_v0.snapshot import SessionView, WorldSnapshot


@dataclass(frozen=True)
class SportRuleDecision:
    action: Literal["allow", "pending", "block"]
    reason: str
    risk_level: Literal["low", "medium", "high"]


def evaluate_plan_patch_sport_rules(
    draft: PlanPatchDraft,
    snapshot: WorldSnapshot,
) -> SportRuleDecision:
    sessions = {session.id: session for session in snapshot.current_plan}
    operations = draft.operations

    for operation in operations:
        source = sessions.get(operation.source_session_id)
        if source is not None and source.status == "done":
            return _block("done_session_protected", "medium")

    if _creates_hard(operations, sessions) and _has_active_health_fact(snapshot):
        return _block("health_fact_blocks_hard", "high")

    if _creates_hard_density(operations, sessions, snapshot):
        return _block("hard_session_too_dense", "high")

    if len(operations) > 1:
        return _pending("multi_operation_requires_confirmation")

    touched = [sessions[operation.source_session_id] for operation in operations if operation.source_session_id in sessions]
    if any(session.priority == "key" for session in touched):
        return _pending("key_session_requires_confirmation")

    return SportRuleDecision(action="allow", reason="low_risk_plan_patch", risk_level="low")


def _creates_hard(
    operations: tuple[PlanPatchOperation, ...],
    sessions: dict[int, SessionView],
) -> bool:
    return any(_effective_is_hard(operation, sessions) for operation in operations)


def _creates_hard_density(
    operations: tuple[PlanPatchOperation, ...],
    sessions: dict[int, SessionView],
    snapshot: WorldSnapshot,
) -> bool:
    for operation in operations:
        if not _effective_is_hard(operation, sessions):
            continue
        target_date = _operation_date(operation, sessions)
        if target_date is None:
            continue
        for session in snapshot.current_plan:
            if session.id == operation.source_session_id:
                continue
            if not _is_hard_or_long(session):
                continue
            if abs((session.date - target_date).days) <= 1:
                return True
    return False


def _effective_is_hard(
    operation: PlanPatchOperation,
    sessions: dict[int, SessionView],
) -> bool:
    source = sessions.get(operation.source_session_id)
    if source is None:
        return False
    label = operation.new_intensity_label or source.intensity_label
    duration = operation.new_duration_min if operation.new_duration_min is not None else source.duration_min
    return _is_hard_label(label) or duration >= 90


def _operation_date(
    operation: PlanPatchOperation,
    sessions: dict[int, SessionView],
) -> date | None:
    if operation.target_date is not None:
        return operation.target_date
    source = sessions.get(operation.source_session_id)
    return source.date if source is not None else None


def _is_hard_or_long(session: SessionView) -> bool:
    return _is_hard_label(session.intensity_label) or session.duration_min >= 90


def _is_hard_label(value: str) -> bool:
    return value.strip().lower() in {"hard", "high", "intense"}


def _has_active_health_fact(snapshot: WorldSnapshot) -> bool:
    return any(fact.kind == "health" and fact.confidence >= 0.5 for fact in snapshot.active_facts)


def _block(reason: str, risk_level: Literal["medium", "high"]) -> SportRuleDecision:
    return SportRuleDecision(action="block", reason=reason, risk_level=risk_level)


def _pending(reason: str) -> SportRuleDecision:
    return SportRuleDecision(action="pending", reason=reason, risk_level="medium")
