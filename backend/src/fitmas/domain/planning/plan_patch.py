from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fitmas.domain.planning.mutation_hooks import run_pre_mutation_hooks
from fitmas.core.time_context import get_local_now

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
    suggested_fix: str | None = None


@dataclass(frozen=True, slots=True)
class PlanPatchValidation:
    status: PlanPatchValidationStatus
    operation_results: tuple[PlanPatchOperationValidation, ...]
    summary: str = ""


def adapt_plan_patch_to_mutation_decisions(patch: PlanPatch) -> list[MutationDecision]:
    """Convert a coach-authored PlanPatch to the legacy mutation executor shape."""
    return [
        _operation_to_mutation_decision(operation, fitmas_message=patch.coach_message)
        for operation in patch.operations
        if operation.operation_type != "create_session"
    ]


def plan_patch_from_mutation_decisions(
    decisions: Sequence[Any],
    *,
    coach_message: str,
    confirmation_reason: str | None = None,
) -> PlanPatch:
    """Convert legacy adaptation suggestions to the PlanPatch confirmation shape."""
    operations: list[PlanPatchOperation] = []
    for decision in decisions:
        mutation_type = str(_value(decision, "mutation_type") or "").strip()
        if not mutation_type or mutation_type == "no_change":
            continue
        operations.append(
            PlanPatchOperation(
                operation_type=mutation_type,
                target_session_id=_optional_int(_value(decision, "target_session_id")),
                second_session_id=_optional_int(_value(decision, "second_session_id")),
                target_date=_optional_str(_value(decision, "target_date")),
                from_day=_optional_str(_value(decision, "from_day")),
                to_day=_optional_str(_value(decision, "to_day")),
                new_title=_optional_str(_value(decision, "new_title")),
                new_goal=_optional_str(_value(decision, "new_goal")),
                new_sport_type=_optional_str(_value(decision, "new_sport_type")),
                new_session_type=_optional_str(_value(decision, "new_session_type")),
                new_duration_min=_optional_int(_value(decision, "new_duration_min")),
                new_intensity=_optional_str(_value(decision, "new_intensity")),
                new_description=_optional_str(_value(decision, "new_description")),
                rationale=str(_value(decision, "rationale") or "Adaptation proactive a confirmer."),
            )
        )
    return PlanPatch(
        coach_message=coach_message,
        confirmation_reason=confirmation_reason,
        operations=operations,
    )


def validate_plan_patch(
    db: Session,
    *,
    plan_id: int,
    patch: PlanPatch,
    scheduled_sessions: Sequence[Any] = (),
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> PlanPatchValidation:
    operation_results: list[PlanPatchOperationValidation] = []
    for operation in patch.operations:
        if operation.operation_type == "create_session":
            operation_results.append(
                _validate_create_session_operation(
                    operation,
                    scheduled_sessions=scheduled_sessions,
                    timezone_name=timezone_name,
                    now=now,
                )
            )
            continue
        target_validation = _validate_existing_session_targets(operation, scheduled_sessions=scheduled_sessions)
        if target_validation is not None:
            operation_results.append(target_validation)
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
        status = _status_from_pre_result(allowed=pre_result.allowed, warning_codes=warning_codes)
        if status == "valid" and _is_ambiguous_existing_session_reference(operation, scheduled_sessions=scheduled_sessions):
            warning_codes = (*warning_codes, "ambiguous_target_reference")
            warning_messages = (*warning_messages, "Plusieurs seances du meme sport peuvent correspondre a cette reference.")
            status = "requires_confirmation"
        operation_results.append(
            PlanPatchOperationValidation(
                operation_type=operation.operation_type,
                status=status,
                target_session_id=operation.target_session_id,
                block_reason=pre_result.block_reason,
                warning_codes=warning_codes,
                warning_messages=warning_messages,
                suggested_fix=_suggested_fix_for_operation(
                    operation,
                    block_reason=pre_result.block_reason,
                    warning_codes=warning_codes,
                    scheduled_sessions=scheduled_sessions,
                ),
            )
        )
    results = tuple(operation_results)
    return PlanPatchValidation(
        status=_aggregate_status(tuple(result.status for result in results)),
        operation_results=results,
        summary=_build_validation_summary(results),
    )


def _validate_create_session_operation(
    operation: PlanPatchOperation,
    *,
    scheduled_sessions: Sequence[Any],
    timezone_name: str | None,
    now: datetime | None,
) -> PlanPatchOperationValidation:
    target_date = _parse_iso_date(operation.target_date)
    if target_date is None:
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="missing_target_date",
            suggested_fix="Renseigner target_date au format YYYY-MM-DD.",
        )
    local_today = get_local_now(timezone_name, now=now).date()
    if target_date < local_today:
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="past_target_date",
            suggested_fix="Choisir une date future.",
        )
    if not str(operation.new_sport_type or "").strip():
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="missing_sport_type",
            suggested_fix="Renseigner new_sport_type.",
        )
    if not str(operation.new_title or "").strip():
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="missing_title",
            suggested_fix="Renseigner new_title.",
        )
    if operation.new_duration_min is None or int(operation.new_duration_min or 0) <= 0:
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="missing_duration",
            suggested_fix="Renseigner new_duration_min avec une duree positive.",
        )
    if _has_occupied_training_target(scheduled_sessions, target_date=target_date, timezone_name=timezone_name):
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="occupied_training_target",
            suggested_fix="Utiliser swap_sessions ou choisir un jour sans seance stable.",
        )
    return PlanPatchOperationValidation(
        operation_type=operation.operation_type,
        status="valid",
    )


def _validate_existing_session_targets(
    operation: PlanPatchOperation,
    *,
    scheduled_sessions: Sequence[Any],
) -> PlanPatchOperationValidation | None:
    if operation.target_session_id is None:
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            block_reason="missing_target_session_id",
            suggested_fix="Relire le planning actuel et renseigner target_session_id.",
        )
    if _find_scheduled_session(scheduled_sessions, operation.target_session_id) is None:
        return PlanPatchOperationValidation(
            operation_type=operation.operation_type,
            status="blocked",
            target_session_id=operation.target_session_id,
            block_reason="target_session_not_found",
            suggested_fix="Relire le planning actuel et cibler une session active.",
        )
    if operation.operation_type == "swap_sessions":
        if operation.second_session_id is None:
            return PlanPatchOperationValidation(
                operation_type=operation.operation_type,
                status="blocked",
                target_session_id=operation.target_session_id,
                block_reason="missing_second_session_id",
                suggested_fix="Relire le planning actuel et renseigner second_session_id.",
            )
        if _find_scheduled_session(scheduled_sessions, operation.second_session_id) is None:
            return PlanPatchOperationValidation(
                operation_type=operation.operation_type,
                status="blocked",
                target_session_id=operation.target_session_id,
                block_reason="second_session_not_found",
                suggested_fix="Relire le planning actuel et cibler deux sessions actives.",
            )
    return None


def _is_ambiguous_existing_session_reference(
    operation: PlanPatchOperation,
    *,
    scheduled_sessions: Sequence[Any],
) -> bool:
    if operation.operation_type not in {"move_session", "swap_sessions"}:
        return False
    if str(operation.from_day or "").strip():
        return False
    target = _find_scheduled_session(scheduled_sessions, operation.target_session_id)
    if target is None:
        return False
    target_sport = str(_value(target, "sport_type") or "").strip().lower()
    if not target_sport or target_sport in {"rest", "off"}:
        return False
    candidates = [
        session
        for session in scheduled_sessions
        if str(_value(session, "sport_type") or "").strip().lower() == target_sport
        and str(_value(session, "completion_status") or "").strip().lower() not in {"done", "skipped", "canceled"}
    ]
    return len(candidates) > 1


def _operation_to_mutation_decision(operation: PlanPatchOperation, *, fitmas_message: str) -> MutationDecision:
    from fitmas.domain.planning.mutation_decision import MutationDecision

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


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None


def _suggested_fix_for_operation(
    operation: PlanPatchOperation,
    *,
    block_reason: str | None,
    warning_codes: tuple[str, ...],
    scheduled_sessions: Sequence[Any],
) -> str | None:
    codes = set(warning_codes)
    if block_reason == "same_sport_proximity":
        target = _find_scheduled_session(scheduled_sessions, operation.target_session_id)
        sport_type = str(_value(target, "sport_type") or "meme sport").strip().lower()
        session_type = str(_value(target, "session_type") or "meme type").strip().lower()
        return f"Choisir une date a plus de 48h de l'autre {sport_type}/{session_type}."
    if block_reason == "occupied_training_target":
        return "Utiliser swap_sessions ou choisir un jour sans seance stable."
    if block_reason == "completed_session_target":
        return "Cibler une seance encore planifiee; ne pas modifier une seance deja faite ou skippee."
    if block_reason in {
        "missing_target_session_id",
        "target_session_not_found",
        "missing_second_session_id",
        "second_session_not_found",
    }:
        return "Relire le planning actuel et cibler une session active."
    if "hard_session_limit" in codes:
        return "Transformer la seance en easy ou deplacer une autre seance intense."
    if "hard_session_collision" in codes:
        return "Choisir un jour sans autre seance intense."
    if "replace_key_session_changes_sport" in codes:
        return "Demander confirmation avant de changer le sport d'une seance cle."
    if "ambiguous_target_reference" in codes:
        return "Demander confirmation: plusieurs seances du meme sport peuvent correspondre."
    if "move_to_past" in codes:
        return "Choisir une date future."
    return None


def _find_scheduled_session(scheduled_sessions: Sequence[Any], session_id: int | None) -> Any | None:
    if session_id is None:
        return None
    for session in scheduled_sessions:
        if _value(session, "id") == session_id:
            return session
    return None


def _build_validation_summary(results: tuple[PlanPatchOperationValidation, ...]) -> str:
    if not results:
        return "Patch vide."
    blocked = next((result for result in results if result.status == "blocked"), None)
    if blocked is not None:
        reason = blocked.block_reason or ",".join(blocked.warning_codes) or "blocked"
        return f"Patch bloque: {blocked.operation_type} {reason}."
    confirmation = next((result for result in results if result.status == "requires_confirmation"), None)
    if confirmation is not None:
        reason = confirmation.block_reason or ",".join(confirmation.warning_codes) or "requires_confirmation"
        return f"Patch a confirmer: {confirmation.operation_type} {reason}."
    warning = next((result for result in results if result.status == "warning"), None)
    if warning is not None:
        reason = warning.block_reason or ",".join(warning.warning_codes) or "warning"
        return f"Patch avec avertissement: {warning.operation_type} {reason}."
    return "Patch valide."


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
