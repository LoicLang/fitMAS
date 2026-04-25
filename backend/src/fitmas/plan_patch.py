from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fitmas.mutation_hooks import run_pre_mutation_hooks
from fitmas.time_context import get_local_now

PlanPatchOperationType = Literal[
    "move_session",
    "swap_sessions",
    "replace_session",
    "update_session",
    "lighten_day",
    "create_session",
]
PlanPatchValidationStatus = Literal["valid", "warning", "requires_confirmation", "blocked"]


class PlanPatchOperation(BaseModel):
    operation_type: PlanPatchOperationType
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


class PlanPatch(BaseModel):
    operations: list[PlanPatchOperation] = Field(default_factory=list)
    coach_message: str
    confirmation_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlanPatchOperationValidation:
    operation_type: str
    status: PlanPatchValidationStatus
    target_session_id: int | None = None
    block_reason: str | None = None
    warning_codes: tuple[str, ...] = ()
    warning_messages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanPatchValidation:
    status: PlanPatchValidationStatus
    operation_results: tuple[PlanPatchOperationValidation, ...]


def adapt_plan_patch_to_mutation_decisions(patch: PlanPatch) -> list[MutationDecision]:
    """Convert a coach-authored PlanPatch to the legacy mutation executor shape."""
    return [
        _operation_to_mutation_decision(operation, fitmas_message=patch.coach_message)
        for operation in patch.operations
        if operation.operation_type != "create_session"
    ]


def validate_plan_patch(
    db: Session,
    *,
    plan_id: int,
    patch: PlanPatch,
    scheduled_sessions: Sequence[Any] = (),
    timezone_name: str | None = None,
) -> PlanPatchValidation:
    operation_results: list[PlanPatchOperationValidation] = []
    for operation in patch.operations:
        if operation.operation_type == "create_session":
            operation_results.append(
                _validate_create_session_operation(
                    operation,
                    scheduled_sessions=scheduled_sessions,
                    timezone_name=timezone_name,
                )
            )
            continue
        decision = _operation_to_mutation_decision(operation, fitmas_message=patch.coach_message)
        pre_result = run_pre_mutation_hooks(
            db,
            plan_id,
            decision,
            scheduled_sessions=scheduled_sessions,
            timezone_name=timezone_name,
        )
        warning_codes = tuple(warning.code for warning in pre_result.warnings)
        warning_messages = tuple(warning.message for warning in pre_result.warnings)
        operation_results.append(
            PlanPatchOperationValidation(
                operation_type=operation.operation_type,
                status=_status_from_pre_result(allowed=pre_result.allowed, warning_codes=warning_codes),
                target_session_id=operation.target_session_id,
                block_reason=pre_result.block_reason,
                warning_codes=warning_codes,
                warning_messages=warning_messages,
            )
        )
    return PlanPatchValidation(
        status=_aggregate_status(tuple(result.status for result in operation_results)),
        operation_results=tuple(operation_results),
    )


def _validate_create_session_operation(
    operation: PlanPatchOperation,
    *,
    scheduled_sessions: Sequence[Any],
    timezone_name: str | None,
) -> PlanPatchOperationValidation:
    target_date = _parse_iso_date(operation.target_date)
    if target_date is None:
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="missing_target_date",
        )
    local_today = get_local_now(timezone_name).date()
    if target_date < local_today:
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="past_target_date",
        )
    if not str(operation.new_sport_type or "").strip():
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="missing_sport_type",
        )
    if not str(operation.new_title or "").strip():
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="missing_title",
        )
    if operation.new_duration_min is None or int(operation.new_duration_min or 0) <= 0:
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="missing_duration",
        )
    if _has_occupied_training_target(scheduled_sessions, target_date=target_date, timezone_name=timezone_name):
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="occupied_training_target",
        )
    return PlanPatchOperationValidation(
        operation_type=operation.operation_type,
        status="valid",
    )


def _operation_to_mutation_decision(operation: PlanPatchOperation, *, fitmas_message: str) -> MutationDecision:
    from fitmas.llm import MutationDecision

    return MutationDecision(
        mutation_type=operation.operation_type,
        target_session_id=operation.target_session_id,
        second_session_id=operation.second_session_id,
        target_date=operation.target_date,
        from_day=operation.from_day,
        to_day=operation.to_day,
        new_title=operation.new_title,
        new_goal=operation.new_goal,
        new_sport_type=operation.new_sport_type,
        new_session_type=operation.new_session_type,
        new_duration_min=operation.new_duration_min,
        new_intensity=operation.new_intensity,
        new_description=operation.new_description,
        rationale=operation.rationale,
        fitmas_message=fitmas_message,
    )


def _parse_iso_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _has_occupied_training_target(
    scheduled_sessions: Sequence[Any],
    *,
    target_date: date,
    timezone_name: str | None,
) -> bool:
    for session in scheduled_sessions:
        session_date = _local_date(_value(session, "scheduled_date"), timezone_name=timezone_name)
        if session_date != target_date:
            continue
        sport_type = str(_value(session, "sport_type") or "").strip().lower()
        session_type = str(_value(session, "session_type") or "").strip().lower()
        flexibility = str(_value(session, "flexibility") or "").strip().lower()
        if sport_type in {"rest", "off", ""} or session_type in {"rest", "recovery", "mobility"} or flexibility == "flexible":
            continue
        return True
    return False


def _local_date(value: Any, *, timezone_name: str | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return _parse_iso_date(value)
    return None


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _status_from_pre_result(*, allowed: bool, warning_codes: tuple[str, ...]) -> PlanPatchValidationStatus:
    if not allowed:
        return "blocked"
    if warning_codes:
        return "requires_confirmation"
    return "valid"


def _aggregate_status(statuses: tuple[PlanPatchValidationStatus, ...]) -> PlanPatchValidationStatus:
    if any(status == "blocked" for status in statuses):
        return "blocked"
    if any(status == "requires_confirmation" for status in statuses):
        return "requires_confirmation"
    if any(status == "warning" for status in statuses):
        return "warning"
    return "valid"
