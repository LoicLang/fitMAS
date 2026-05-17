from __future__ import annotations

from typing import Any, Mapping

from fitmas.decision import CoachUnderstanding, PendingResolution, RequestedPlanChange, UserSignal
from fitmas.legacy.coach_decision_artifact import (
    LegacyCoachDecisionArtifact,
    legacy_decision_artifact_from_raw,
)
from fitmas.llm import CoachDecision, MutationDecision


def coach_decision_to_understanding(decision: CoachDecision | MutationDecision) -> CoachUnderstanding:
    return coach_decision_artifact_to_understanding(legacy_decision_artifact_from_raw(decision))


def coach_decision_artifact_to_understanding(artifact: LegacyCoachDecisionArtifact) -> CoachUnderstanding:
    signals = _signals_from_decision_artifact(artifact)
    pending_resolution = _pending_resolution_from_decision_artifact(artifact)
    requested_change = _requested_change_from_decision_artifact(artifact)
    intent = _intent_from_decision_artifact(
        artifact,
        signals=signals,
        pending_resolution=pending_resolution,
        requested_change=requested_change,
    )

    return CoachUnderstanding(
        intent=intent,
        confidence=_confidence_from_signals(signals),
        user_summary=_rationale(artifact),
        extracted_signals=signals,
        requested_change=requested_change,
        pending_resolution=pending_resolution,
        clarification_need=None,
    )


def _signals_from_decision_artifact(artifact: LegacyCoachDecisionArtifact) -> tuple[UserSignal, ...]:
    if artifact.mutation_decision is not None and artifact.response_type == "mutation_decision":
        return ()
    signals: list[UserSignal] = []
    for action in artifact.memory_actions:
        signal = _signal_from_memory_action(action)
        if signal is not None:
            signals.append(signal)
    for action in artifact.execution_actions:
        signals.append(_signal_from_execution_action(action))
    return tuple(signals)


def _signal_from_memory_action(action: Any) -> UserSignal | None:
    action_type = str(getattr(action, "type", "") or "")
    payload = _model_payload(action)

    if action_type == "record_health_signal":
        return UserSignal(
            type="health",
            label=str(payload.get("signal_kind") or "other"),
            status=str(payload.get("status") or "unknown"),
            severity=str(payload.get("severity") or "unknown"),
            confidence=_confidence(payload),
            evidence=_optional_str(payload.get("evidence") or payload.get("health_signal")),
            payload=payload,
        )
    if action_type == "record_availability":
        return UserSignal(
            type="availability",
            label=str(payload.get("availability") or "unknown"),
            status=str(payload.get("availability") or "unknown"),
            severity="unknown",
            confidence=_confidence(payload),
            evidence=_optional_str(payload.get("evidence") or payload.get("window_text")),
            payload=payload,
        )
    if action_type == "record_preference":
        return UserSignal(
            type="preference",
            label=str(payload.get("polarity") or "unknown"),
            status=str(payload.get("polarity") or "unknown"),
            severity="unknown",
            confidence=_confidence(payload),
            evidence=_optional_str(payload.get("evidence") or payload.get("preference")),
            payload=payload,
        )
    return None


def _signal_from_execution_action(action: Any) -> UserSignal:
    payload = _model_payload(action)
    return UserSignal(
        type="execution",
        label=str(payload.get("status") or "unknown"),
        status=str(payload.get("status") or "unknown"),
        severity="unknown",
        confidence=_confidence(payload),
        evidence=_optional_str(payload.get("evidence") or payload.get("target_ref")),
        payload=payload,
    )


def _pending_resolution_from_decision_artifact(artifact: LegacyCoachDecisionArtifact) -> PendingResolution | None:
    if artifact.mutation_decision is not None and artifact.response_type == "mutation_decision":
        return None
    resolution = artifact.pending_resolution
    if resolution is None:
        return None
    payload = _model_payload(resolution)
    return PendingResolution(
        type=str(payload.get("type") or "ignore"),
        reason=_optional_str(payload.get("reason")),
        selected_candidate_id=_optional_str(payload.get("selected_candidate_id")),
        requested_changes=_optional_str(payload.get("requested_changes")),
        question=_optional_str(payload.get("question")),
    )


def _requested_change_from_decision_artifact(artifact: LegacyCoachDecisionArtifact) -> RequestedPlanChange | None:
    response_type = str(artifact.response_type or "")
    if response_type == "mutation_decision" and artifact.mutation_decision is not None:
        return _requested_change_from_mutation_decision(artifact.mutation_decision)
    if response_type in {"plan_patch", "requires_confirmation"} and artifact.plan_patch is not None:
        return _requested_change_from_plan_patch(artifact.plan_patch, reason=_rationale(artifact))
    return None


def _requested_change_from_mutation_decision(decision: MutationDecision) -> RequestedPlanChange | None:
    mutation_type = str(getattr(decision, "mutation_type", "") or "")
    if mutation_type == "no_change":
        return None
    return RequestedPlanChange(
        kind=_kind_from_mutation_type(mutation_type),
        source_ref=_source_ref_from_target(getattr(decision, "target_session_id", None)),
        target_ref=_target_ref_from_mutation(decision),
        desired_sport=_optional_str(getattr(decision, "new_sport_type", None)),
        desired_duration_min=getattr(decision, "new_duration_min", None),
        desired_intensity=_optional_str(getattr(decision, "new_intensity", None)),
        reason=_rationale(decision),
        risk_signals=(),
    )


def _requested_change_from_plan_patch(patch: Any, *, reason: str) -> RequestedPlanChange:
    operations = tuple(getattr(patch, "operations", ()) or ())
    first = operations[0] if operations else None
    operation_types = {str(getattr(operation, "operation_type", "") or "") for operation in operations}

    return RequestedPlanChange(
        kind=_kind_from_operation_types(operation_types),
        source_ref=_source_ref_from_target(getattr(first, "target_session_id", None)),
        target_ref=_target_ref_from_operation(first),
        desired_sport=_optional_str(getattr(first, "new_sport_type", None)),
        desired_duration_min=getattr(first, "new_duration_min", None),
        desired_intensity=_optional_str(getattr(first, "new_intensity", None)),
        reason=reason,
        risk_signals=(),
    )


def _intent_from_decision(
    decision: CoachDecision | MutationDecision,
    *,
    signals: tuple[UserSignal, ...],
    pending_resolution: PendingResolution | None,
    requested_change: RequestedPlanChange | None,
) -> str:
    if pending_resolution is not None:
        return "pending_response"
    if requested_change is not None:
        return "plan_change"
    if any(signal.type == "execution" for signal in signals):
        return "execution_report"
    if any(signal.type == "health" for signal in signals):
        return "health_signal"
    if any(signal.type == "availability" for signal in signals):
        return "availability_signal"
    if isinstance(decision, CoachDecision) and decision.response_type == "no_change":
        return "general_answer"
    return "general_answer"


def _intent_from_decision_artifact(
    artifact: LegacyCoachDecisionArtifact,
    *,
    signals: tuple[UserSignal, ...],
    pending_resolution: PendingResolution | None,
    requested_change: RequestedPlanChange | None,
) -> str:
    if pending_resolution is not None:
        return "pending_response"
    if requested_change is not None:
        return "plan_change"
    if any(signal.type == "execution" for signal in signals):
        return "execution_report"
    if any(signal.type == "health" for signal in signals):
        return "health_signal"
    if any(signal.type == "availability" for signal in signals):
        return "availability_signal"
    if artifact.response_type == "no_change":
        return "general_answer"
    return "general_answer"


def _kind_from_mutation_type(mutation_type: str) -> str:
    return {
        "move_session": "move",
        "swap_sessions": "swap",
        "lighten_day": "lighten",
        "replace_session": "replace",
        "update_session": "replace",
        "create_session": "create",
    }.get(mutation_type, "unknown")


def _kind_from_operation_types(operation_types: set[str]) -> str:
    if len(operation_types) != 1:
        return "unknown"
    return _kind_from_mutation_type(next(iter(operation_types)))


def _source_ref_from_target(target_session_id: Any) -> str | None:
    if target_session_id is None:
        return None
    return f"session_id:{target_session_id}"


def _target_ref_from_mutation(decision: MutationDecision) -> str | None:
    target_date = _optional_str(getattr(decision, "target_date", None))
    if target_date:
        return f"date:{target_date}"
    to_day = _optional_str(getattr(decision, "to_day", None))
    if to_day:
        return f"day:{to_day}"
    second_session_id = getattr(decision, "second_session_id", None)
    if second_session_id is not None:
        return f"session_id:{second_session_id}"
    return None


def _target_ref_from_operation(operation: Any) -> str | None:
    if operation is None:
        return None
    target_date = _optional_str(getattr(operation, "target_date", None))
    if target_date:
        return f"date:{target_date}"
    second_session_id = getattr(operation, "second_session_id", None)
    if second_session_id is not None:
        return f"session_id:{second_session_id}"
    return None


def _confidence_from_signals(signals: tuple[UserSignal, ...]) -> float:
    if not signals:
        return 0.7
    return min(1.0, max(0.0, sum(signal.confidence for signal in signals) / len(signals)))


def _confidence(payload: Mapping[str, Any]) -> float:
    value = payload.get("confidence")
    if isinstance(value, int | float):
        return min(1.0, max(0.0, float(value)))
    return 0.75


def _rationale(decision: CoachDecision | MutationDecision | LegacyCoachDecisionArtifact) -> str:
    return str(getattr(decision, "rationale", "") or "").strip()


def _model_payload(value: Any) -> Mapping[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, Mapping):
        return {key: item for key, item in value.items() if item is not None}
    return {}


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
