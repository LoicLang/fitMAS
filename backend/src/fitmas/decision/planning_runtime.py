from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Callable

from sqlalchemy.orm import Session

from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import CoachUnderstanding, RequestedPlanChange
from fitmas.domain.planning.decision_service import decide_plan_change
from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.domain.planning.mutation_service import PlanningCommandService
from fitmas.domain.planning.reference_tokens import (
    is_iso_date,
    normalize_plan_ref,
    plan_ref_kind,
    plan_ref_payload,
    plan_session_ref_ids,
)
from fitmas.decision.planning_outcomes import (
    canonical_planning_blocked_outcome,
    conversation_outcome_from_planning_runtime_result,
)

_SUPPORTED_KINDS = {"move", "swap", "lighten", "replace", "create", "constraint_window"}
_NON_PLANNING_PRIMARY_INTENTS = {
    "availability_constraint",
    "close_turn",
    "execution_report",
    "health_signal",
    "plan_lookup",
}


@dataclass(frozen=True, slots=True)
class PlanningRuntimeAdapterAttempt:
    applicable: bool
    result: PlanningDecisionResult | None
    reason: str


def run_planning_runtime_attempt_from_understanding(
    *,
    understanding: CoachUnderstanding | None,
    context: Any,
    db: Session,
    user: Any,
    source_text: str,
    coach_state_bundle: Any | None,
    reviewer_request_json_fn,
) -> PlanningRuntimeAdapterAttempt:
    if understanding is None:
        return PlanningRuntimeAdapterAttempt(
            applicable=False,
            result=None,
            reason="missing_understanding",
        )
    if understanding.requested_change is None:
        return PlanningRuntimeAdapterAttempt(
            applicable=False,
            result=None,
            reason="no_requested_plan_change",
        )

    planning_decision = decide_plan_change(
        understanding.requested_change,
        context=context,
        db=db,
        user=user,
        coach_state_bundle=coach_state_bundle,
        reviewer_request_json_fn=reviewer_request_json_fn,
    )
    if not isinstance(planning_decision, PlanningDecisionResult):
        return PlanningRuntimeAdapterAttempt(
            applicable=True,
            result=planning_decision,
            reason="non_standard_planning_result",
        )

    command_result = PlanningCommandService(db=db, user=user).apply(
        planning_decision,
        source_text=source_text,
        coach_state_bundle=coach_state_bundle,
        activities=tuple(getattr(getattr(context, "execution", None), "activities", ()) or ()),
        active_facts=tuple(getattr(getattr(context, "memory", None), "active_facts", ()) or ()),
    )
    return PlanningRuntimeAdapterAttempt(
        applicable=True,
        result=replace(
            planning_decision,
            command_result=command_result,
            pending_confirmation_id=command_result.pending_confirmation_id,
        ),
        reason="handled",
    )
_TURN_PLAN_ACTION_KIND = {
    "move_session": "move",
    "swap_sessions": "swap",
    "lighten_day": "lighten",
    "replace_session": "replace",
    "create_session": "create",
}


def canonical_planning_provider_enabled() -> bool:
    return _env_flag_enabled("FITMAS_CANONICAL_PLANNING_PROVIDER", default=True)


def trace_canonical_planning_prepared(
    turn_context: dict[str, object],
    *,
    turn_plan: Any,
    pending_confirmation: Any,
) -> None:
    raw_flag = os.getenv("FITMAS_CANONICAL_PLANNING_PROVIDER")
    turn_context["canonical_planning_provider"] = {
        "source": "coach_understanding",
        "enabled": canonical_planning_provider_enabled(),
        "default_enabled": True,
        "env_value": raw_flag,
        "applicable": None,
        "result": "prepared",
        "fallback_reason": None,
        "turn_primary_intent": str(getattr(turn_plan, "primary_intent", "") or ""),
        "has_active_pending": _has_active_pending(pending_confirmation),
    }


def should_use_canonical_planning_without_legacy(
    *,
    understanding: CoachUnderstanding | None,
    turn_plan: Any,
    pending_confirmation: Any,
) -> bool:
    if not canonical_planning_provider_enabled():
        return False
    if understanding is None:
        return False
    if understanding.intent != "plan_change":
        return False
    if understanding.requested_change is None:
        return False
    if understanding.pending_resolution is not None or _has_active_pending(pending_confirmation):
        return False
    if _has_blocking_command_signals(understanding):
        return False
    if not _turn_plan_allows_planning(turn_plan):
        return False
    return _requested_change_is_supported(understanding.requested_change)


def should_handle_unsupported_canonical_planning_without_legacy(
    *,
    understanding: CoachUnderstanding | None,
    turn_plan: Any,
    pending_confirmation: Any,
) -> bool:
    if not canonical_planning_provider_enabled():
        return False
    if understanding is None:
        return False
    if understanding.pending_resolution is not None or _has_active_pending(pending_confirmation):
        return False
    if not _turn_plan_allows_planning(turn_plan):
        return False
    if understanding.intent != "plan_change":
        return True
    if understanding.requested_change is None:
        return True
    if not _requested_change_is_supported(understanding.requested_change):
        return True
    return False


def planning_understanding_for_provider(
    *,
    understanding: CoachUnderstanding | None,
    turn_plan: Any,
) -> CoachUnderstanding | None:
    if understanding is not None and understanding.intent == "plan_change" and understanding.requested_change is not None:
        understanding = _understanding_with_normalized_requested_change(understanding)
        if _requested_change_is_supported(understanding.requested_change) and not _has_blocking_command_signals(understanding):
            return understanding
    if not _turn_plan_allows_planning(turn_plan):
        return understanding
    requested_change = _requested_change_from_sport_availability(
        turn_plan=turn_plan,
        understanding=understanding,
    )
    if requested_change is not None:
        return CoachUnderstanding(
            intent="plan_change",
            confidence=_confidence_from_turn_plan(turn_plan, understanding=understanding),
            user_summary=str(
                getattr(turn_plan, "user_goal", "") or getattr(understanding, "user_summary", "") or ""
            ).strip(),
            extracted_signals=tuple(getattr(understanding, "extracted_signals", ()) or ()),
            requested_change=requested_change,
            pending_resolution=None,
            clarification_need=None,
        )
    requested_change = _requested_change_from_availability_window(
        turn_plan=turn_plan,
        understanding=understanding,
    )
    if requested_change is not None:
        return CoachUnderstanding(
            intent="plan_change",
            confidence=_confidence_from_turn_plan(turn_plan, understanding=understanding),
            user_summary=str(
                getattr(turn_plan, "user_goal", "") or getattr(understanding, "user_summary", "") or ""
            ).strip(),
            extracted_signals=tuple(getattr(understanding, "extracted_signals", ()) or ()),
            requested_change=requested_change,
            pending_resolution=None,
            clarification_need=None,
        )
    requested_change = _requested_change_from_turn_plan(
        turn_plan,
        fallback_requested_change=understanding.requested_change if understanding is not None else None,
    )
    if requested_change is None:
        return understanding
    return CoachUnderstanding(
        intent="plan_change",
        confidence=_confidence_from_turn_plan(turn_plan, understanding=understanding),
        user_summary=str(
            getattr(turn_plan, "user_goal", "") or getattr(understanding, "user_summary", "") or ""
        ).strip(),
        extracted_signals=tuple(getattr(understanding, "extracted_signals", ()) or ()),
        requested_change=requested_change,
        pending_resolution=None,
        clarification_need=None,
    )


def trace_canonical_planning_not_used(
    turn_context: dict[str, object],
    *,
    understanding: CoachUnderstanding | None,
    turn_plan: Any,
    pending_confirmation: Any,
) -> None:
    trace = _canonical_planning_trace(turn_context)
    trace.update(
        {
            "applicable": False,
            "result": "fallback_legacy",
            "fallback_reason": canonical_planning_fallback_reason(
                understanding=understanding,
                turn_plan=turn_plan,
                pending_confirmation=pending_confirmation,
            ),
        }
    )


def canonical_planning_fallback_reason(
    *,
    understanding: CoachUnderstanding | None,
    turn_plan: Any,
    pending_confirmation: Any,
) -> str:
    if not canonical_planning_provider_enabled():
        return "provider_disabled"
    if understanding is None:
        return "missing_understanding"
    if understanding.intent != "plan_change":
        return f"intent:{understanding.intent}"
    if understanding.requested_change is None:
        return "missing_requested_change"
    if understanding.pending_resolution is not None:
        return "pending_resolution_present"
    if _has_active_pending(pending_confirmation):
        return "active_pending"
    if _has_blocking_command_signals(understanding):
        return "blocking_command_signals"
    if not _turn_plan_allows_planning(turn_plan):
        return "turn_plan_not_planning"
    if not _requested_change_is_supported(understanding.requested_change):
        return "unsupported_requested_change"
    return "unknown"


def should_prepare_canonical_planning_understanding(
    *,
    turn_plan: Any,
    pending_confirmation: Any,
) -> bool:
    if not canonical_planning_provider_enabled():
        return False
    if _has_active_pending(pending_confirmation):
        return False
    return _turn_plan_allows_planning(turn_plan)


def handle_canonical_planning(
    *,
    understanding: CoachUnderstanding,
    context: Any,
    db: Any,
    user: Any,
    source_text: str,
    coach_state_bundle: Any | None,
    reviewer_request_json_fn,
    grounding_facts: tuple[str, ...],
    decision_reply_composer_fn: Callable[[], Any],
    turn_context: dict[str, object],
) -> ConversationTurnOutcome | None:
    if not _requested_change_is_supported(understanding.requested_change):
        trace = _canonical_planning_trace(turn_context)
        trace.update(
            {
                "intent": understanding.intent,
                "applicable": False,
                "result": "blocked",
                "attempt_reason": "unsupported_requested_change",
                "fallback_reason": None,
            }
        )
        _trace_legacy_skipped(turn_context)
        return canonical_planning_blocked_outcome(
            reason=_unsupported_requested_change_reason(understanding.requested_change),
            user_text=source_text,
            grounding_facts=grounding_facts,
            decision_reply_composer_fn=decision_reply_composer_fn,
        )

    trace = _canonical_planning_trace(turn_context)
    trace.update(
        {
            "intent": understanding.intent,
            "applicable": True,
            "result": "applicable",
            "fallback_reason": None,
        }
    )
    _trace_legacy_skipped(turn_context)
    attempt = run_planning_runtime_attempt_from_understanding(
        understanding=understanding,
        context=context,
        db=db,
        user=user,
        source_text=source_text,
        coach_state_bundle=coach_state_bundle,
        reviewer_request_json_fn=reviewer_request_json_fn,
    )
    if attempt.result is not None:
        trace["result"] = "handled"
        trace["attempt_reason"] = attempt.reason
        return conversation_outcome_from_planning_runtime_result(
            attempt.result,
            db=db,
            user=user,
            user_text=source_text,
            grounding_facts=grounding_facts,
            original_reply="",
            turn_context=turn_context,
            action_result={},
            decision_reply_composer_fn=decision_reply_composer_fn,
            compose_no_change_reply_for_turn_fn=None,
        )
    if attempt.applicable:
        trace["result"] = "blocked"
        trace["attempt_reason"] = attempt.reason
        return canonical_planning_blocked_outcome(
            reason=attempt.reason,
            user_text=source_text,
            grounding_facts=grounding_facts,
            decision_reply_composer_fn=decision_reply_composer_fn,
        )

    trace["result"] = "fallback_legacy"
    trace["attempt_reason"] = attempt.reason
    trace["fallback_reason"] = attempt.reason
    return None


def _requested_change_from_turn_plan(
    turn_plan: Any,
    *,
    fallback_requested_change: RequestedPlanChange | None = None,
) -> RequestedPlanChange | None:
    action = str(getattr(turn_plan, "planning_action", "") or "").strip()
    kind = _TURN_PLAN_ACTION_KIND.get(action)
    if kind is None:
        return None
    refs = tuple(
        ref
        for ref in (_ref_from_temporal_reference(item) for item in tuple(getattr(turn_plan, "temporal_references", ()) or ()))
        if ref is not None
    )
    if kind == "swap":
        if len(refs) < 2:
            return None
        source_ref, target_ref = refs[0], refs[1]
    elif kind == "move":
        source_ref = _machine_source_ref(fallback_requested_change) or _temporal_ref_by_role(turn_plan, "source")
        target_ref = _machine_target_ref(fallback_requested_change) or _temporal_ref_by_role(turn_plan, "target")
        if source_ref is None or target_ref is None:
            return None
    elif kind in {"lighten", "replace"}:
        source_ref = (
            _machine_source_ref(fallback_requested_change)
            or _temporal_ref_by_role(turn_plan, "source")
            or _temporal_ref_by_role(turn_plan, "target")
            or _single_temporal_ref(turn_plan)
        )
        target_ref = None
        if source_ref is None:
            return None
    elif kind == "create":
        source_ref = None
        target_ref = (
            _machine_target_ref(fallback_requested_change)
            or _temporal_ref_by_role(turn_plan, "target")
            or _single_temporal_ref(turn_plan)
        )
        if target_ref is None:
            return None
    else:
        return None
    return RequestedPlanChange(
        kind=kind,
        source_ref=source_ref,
        target_ref=target_ref,
        desired_sport=_fallback_desired_sport(fallback_requested_change),
        desired_duration_min=_fallback_desired_duration(fallback_requested_change),
        desired_intensity=_fallback_desired_intensity(fallback_requested_change),
        reason=str(getattr(turn_plan, "user_goal", "") or "Demande planning typee par TurnPlan.").strip(),
        risk_signals=(),
    )


def _understanding_with_normalized_requested_change(understanding: CoachUnderstanding) -> CoachUnderstanding:
    requested_change = understanding.requested_change
    if requested_change is None:
        return understanding
    normalized = _normalized_requested_change(requested_change)
    if normalized == requested_change:
        return understanding
    return replace(understanding, requested_change=normalized)


def _normalized_requested_change(requested_change: RequestedPlanChange) -> RequestedPlanChange:
    if requested_change.kind == "swap":
        source_ref, target_ref = _normalized_swap_refs(requested_change)
    else:
        source_ref = _normalized_ref_or_original(requested_change.source_ref)
        target_ref = _normalized_ref_or_original(requested_change.target_ref)
    if source_ref == requested_change.source_ref and target_ref == requested_change.target_ref:
        return requested_change
    return replace(requested_change, source_ref=source_ref, target_ref=target_ref)


def _normalized_swap_refs(requested_change: RequestedPlanChange) -> tuple[str | None, str | None]:
    raw_source = requested_change.source_ref
    raw_target = requested_change.target_ref
    source_ids = plan_session_ref_ids(raw_source)
    target_ids = plan_session_ref_ids(raw_target)
    all_ids: list[int] = []
    for session_id in (*source_ids, *target_ids):
        if session_id not in all_ids:
            all_ids.append(session_id)
    if source_ids:
        source_id = source_ids[0]
    elif len(all_ids) >= 2:
        source_id = all_ids[0]
    else:
        source_id = None
    target_id = next((session_id for session_id in all_ids if session_id != source_id), None)
    source_ref = f"session_id:{source_id}" if source_id is not None else _normalized_ref_or_original(raw_source)
    target_ref = f"session_id:{target_id}" if target_id is not None else _normalized_ref_or_original(raw_target)
    return source_ref, target_ref


def _normalized_ref_or_original(raw_ref: str | None) -> str | None:
    normalized = normalize_plan_ref(raw_ref, preserve_unknown=False)
    if normalized is not None:
        return normalized
    return raw_ref


def _unsupported_requested_change_reason(requested_change: RequestedPlanChange | None) -> str:
    if requested_change is None:
        return "il manque le changement planning a evaluer. Je ne touche pas au plan"
    kind = str(getattr(requested_change, "kind", "") or "")
    source_ref = getattr(requested_change, "source_ref", None)
    target_ref = getattr(requested_change, "target_ref", None)
    if kind == "move":
        if not source_ref and not target_ref:
            return "il manque la seance cible et le jour de destination. Je ne touche pas au plan"
        if not source_ref:
            return "il manque la seance exacte a deplacer. Je ne touche pas au plan"
        if not _is_date_like_ref(target_ref):
            return "il manque le jour de destination. Je ne touche pas au plan"
    if kind == "swap":
        return "il manque les deux seances exactes a echanger. Je ne touche pas au plan"
    if kind in {"lighten", "replace"}:
        return "il manque la seance exacte a modifier. Je ne touche pas au plan"
    if kind == "create":
        return "il manque le jour cible de la nouvelle seance. Je ne touche pas au plan"
    return "je ne peux pas resoudre ce changement planning avec assez de certitude. Je ne touche pas au plan"


def _requested_change_from_sport_availability(
    *,
    turn_plan: Any,
    understanding: CoachUnderstanding | None,
) -> RequestedPlanChange | None:
    constraint = _sport_availability_constraint_from_turn_plan(turn_plan)
    if constraint is None:
        constraint = _sport_availability_constraint_from_signals(understanding)
    if constraint is None:
        return None
    sport_type, starts_on, ends_on = constraint
    return RequestedPlanChange(
        kind="replace",
        source_ref=f"sport_window:{sport_type}:{starts_on}:{ends_on}",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity="easy",
        reason=str(
            getattr(turn_plan, "user_goal", "")
            or getattr(understanding, "user_summary", "")
            or "Sport indisponible dans une fenetre typee."
        ).strip(),
        risk_signals=("availability",),
    )


def _requested_change_from_availability_window(
    *,
    turn_plan: Any,
    understanding: CoachUnderstanding | None,
) -> RequestedPlanChange | None:
    constraint = _availability_window_constraint_from_turn_plan(turn_plan)
    if constraint is None:
        constraint = _availability_window_constraint_from_signals(understanding)
    if constraint is None:
        return None
    availability, scope, starts_on, ends_on = constraint
    return RequestedPlanChange(
        kind="constraint_window",
        source_ref=f"availability_window:{availability}:{scope}:{starts_on}:{ends_on}",
        target_ref=None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason=str(
            getattr(turn_plan, "user_goal", "")
            or getattr(understanding, "user_summary", "")
            or "Contrainte large dans une fenetre typee."
        ).strip(),
        risk_signals=("availability",),
    )


def _sport_availability_constraint_from_turn_plan(turn_plan: Any) -> tuple[str, str, str] | None:
    raw = getattr(turn_plan, "availability_constraint", None)
    if not isinstance(raw, dict):
        return None
    return _sport_availability_constraint_from_payload(raw)


def _sport_availability_constraint_from_signals(
    understanding: CoachUnderstanding | None,
) -> tuple[str, str, str] | None:
    if understanding is None:
        return None
    for signal in tuple(getattr(understanding, "extracted_signals", ()) or ()):
        if str(getattr(signal, "type", "") or "") != "availability":
            continue
        constraint = _sport_availability_constraint_from_payload(dict(getattr(signal, "payload", {}) or {}))
        if constraint is not None:
            return constraint
    return None


def _availability_window_constraint_from_turn_plan(turn_plan: Any) -> tuple[str, str, str, str] | None:
    raw = getattr(turn_plan, "availability_constraint", None)
    if not isinstance(raw, dict):
        return None
    return _availability_window_constraint_from_payload(raw)


def _availability_window_constraint_from_signals(
    understanding: CoachUnderstanding | None,
) -> tuple[str, str, str, str] | None:
    if understanding is None:
        return None
    for signal in tuple(getattr(understanding, "extracted_signals", ()) or ()):
        if str(getattr(signal, "type", "") or "") != "availability":
            continue
        constraint = _availability_window_constraint_from_payload(dict(getattr(signal, "payload", {}) or {}))
        if constraint is not None:
            return constraint
    return None


def _sport_availability_constraint_from_payload(payload: dict[str, Any]) -> tuple[str, str, str] | None:
    availability = str(payload.get("availability") or payload.get("status") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    sport_type = str(payload.get("sport_type") or "").strip().lower()
    starts_on = str(payload.get("starts_on") or "").strip()[:10]
    ends_on = str(payload.get("ends_on") or "").strip()[:10]
    if availability not in {"unavailable", "limited"}:
        return None
    if scope != "sport" or not sport_type or not starts_on or not ends_on:
        return None
    if not is_iso_date(starts_on) or not is_iso_date(ends_on):
        return None
    if ends_on < starts_on:
        return None
    return sport_type, starts_on, ends_on


def _availability_window_constraint_from_payload(payload: dict[str, Any]) -> tuple[str, str, str, str] | None:
    availability = _availability_status(payload.get("availability") or payload.get("status"))
    scope = _availability_window_scope(payload.get("scope"))
    starts_on = str(payload.get("starts_on") or "").strip()[:10]
    ends_on = str(payload.get("ends_on") or "").strip()[:10]
    if availability is None:
        return None
    if scope is None or not starts_on or not ends_on:
        return None
    if not is_iso_date(starts_on) or not is_iso_date(ends_on):
        return None
    if ends_on < starts_on:
        return None
    return availability, scope, starts_on, ends_on


def _availability_status(value: object) -> str | None:
    status = str(value or "").strip().lower()
    if status in {"unavailable", "limited"}:
        return status
    return None


def _availability_window_scope(value: object) -> str | None:
    scope = str(value or "").strip().lower()
    if scope in {"general", "time", "location"}:
        return scope
    if scope in {"travel", "trip", "journey", "deplacement", "déplacement"}:
        return "location"
    if scope in {"day", "week", "planning", "plan"}:
        return "general"
    return None


def _machine_source_ref(requested_change: RequestedPlanChange | None) -> str | None:
    if requested_change is None:
        return None
    ref = getattr(requested_change, "source_ref", None)
    return str(ref) if _is_session_role_ref(ref) else None


def _machine_target_ref(requested_change: RequestedPlanChange | None) -> str | None:
    if requested_change is None:
        return None
    ref = getattr(requested_change, "target_ref", None)
    return str(ref) if _is_date_like_ref(ref) else None


def _temporal_ref_by_role(turn_plan: Any, role: str) -> str | None:
    for item in tuple(getattr(turn_plan, "temporal_references", ()) or ()):
        item_role = str(item.get("role") if isinstance(item, dict) else getattr(item, "role", "") or "").strip()
        if item_role == role:
            return _ref_from_temporal_reference(item)
    return None


def _single_temporal_ref(turn_plan: Any) -> str | None:
    refs = tuple(
        ref
        for ref in (_ref_from_temporal_reference(item) for item in tuple(getattr(turn_plan, "temporal_references", ()) or ()))
        if ref is not None
    )
    return refs[0] if len(refs) == 1 else None


def _fallback_desired_sport(requested_change: RequestedPlanChange | None) -> str | None:
    if requested_change is None:
        return None
    value = str(getattr(requested_change, "desired_sport", "") or "").strip()
    return value or None


def _fallback_desired_duration(requested_change: RequestedPlanChange | None) -> int | None:
    if requested_change is None:
        return None
    raw = getattr(requested_change, "desired_duration_min", None)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _fallback_desired_intensity(requested_change: RequestedPlanChange | None) -> str | None:
    if requested_change is None:
        return None
    value = str(getattr(requested_change, "desired_intensity", "") or "").strip()
    return value or None


def _ref_from_temporal_reference(ref: Any) -> str | None:
    if isinstance(ref, dict):
        kind = str(ref.get("kind") or "").strip().lower()
        value = str(ref.get("value") or "").strip()
    else:
        kind = str(getattr(ref, "kind", "") or "").strip().lower()
        value = str(getattr(ref, "value", "") or "").strip()
    if not value:
        return None
    if kind == "date" or _is_iso_date(value):
        return f"date:{value[:10]}"
    if kind in {"weekday", "relative_day"}:
        return f"day:{value}"
    return None


def _confidence_from_turn_plan(turn_plan: Any, *, understanding: CoachUnderstanding | None) -> float:
    raw = getattr(turn_plan, "confidence", None)
    if raw is None and understanding is not None:
        raw = understanding.confidence
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.7


def _requested_change_is_supported(requested_change: Any | None) -> bool:
    if requested_change is None:
        return False
    kind = str(getattr(requested_change, "kind", "") or "").strip()
    if kind not in _SUPPORTED_KINDS:
        return False
    source_ref = getattr(requested_change, "source_ref", None)
    target_ref = getattr(requested_change, "target_ref", None)
    if kind == "move":
        return _is_session_role_ref(source_ref) and _is_date_like_ref(target_ref)
    if kind == "swap":
        return _is_session_role_ref(source_ref) and _is_session_role_ref(target_ref)
    if kind in {"lighten", "replace"}:
        return _is_session_role_ref(source_ref) or (kind == "replace" and _is_sport_window_ref(source_ref))
    if kind == "create":
        return _is_date_like_ref(target_ref)
    if kind == "constraint_window":
        return _is_availability_window_ref(source_ref)
    return False


def _has_blocking_command_signals(understanding: CoachUnderstanding) -> bool:
    command_signals = tuple(signal for signal in understanding.extracted_signals if _signal_would_create_command(signal))
    if not command_signals:
        return False
    if _availability_requested_change(getattr(understanding, "requested_change", None)) and all(
        _signal_would_create_record_availability(signal) for signal in command_signals
    ):
        return False
    if all(_is_nonblocking_planning_sidecar_signal(signal) for signal in understanding.extracted_signals):
        return False
    return True


def _availability_requested_change(requested_change: Any | None) -> bool:
    if requested_change is None:
        return False
    kind = str(getattr(requested_change, "kind", "") or "").strip()
    source_ref = getattr(requested_change, "source_ref", None)
    return (
        kind == "constraint_window" and _is_availability_window_ref(source_ref)
    ) or (
        kind == "replace" and _is_sport_window_ref(source_ref)
    )


def _is_record_availability_command(command: Any) -> bool:
    return (
        str(getattr(command, "domain", "") or "").strip() == "memory"
        and str(getattr(command, "name", "") or "").strip() == "record_availability"
    )


def _signal_would_create_command(signal: Any) -> bool:
    return _signal_action_type(signal) in {
        "record_health_signal",
        "record_availability",
        "record_preference",
        "record_execution_update",
    }


def _signal_would_create_record_availability(signal: Any) -> bool:
    return _signal_action_type(signal) == "record_availability"


def _is_nonblocking_planning_sidecar_signal(signal: Any) -> bool:
    return (
        _is_planning_preference_metadata_signal(signal)
        or _is_planning_availability_metadata_signal(signal)
        or _is_planning_availability_constraint_signal(signal)
        or _is_planning_health_metadata_signal(signal)
    )


def _is_planning_preference_metadata_signal(signal: Any) -> bool:
    payload = dict(getattr(signal, "payload", {}) or {})
    action_type = _signal_action_type(signal)
    scope = str(payload.get("scope") or "").strip()
    signal_type = str(getattr(signal, "type", "") or "").strip()
    return signal_type == "preference" and action_type == "record_preference" and scope in {
        "day",
        "general",
        "session",
        "sport",
        "week",
        "planning",
        "plan",
    }


def _is_planning_availability_metadata_signal(signal: Any) -> bool:
    payload = dict(getattr(signal, "payload", {}) or {})
    action_type = _signal_action_type(signal)
    signal_type = str(getattr(signal, "type", "") or "").strip()
    availability = str(payload.get("availability") or payload.get("status") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    has_durable_anchor = any(
        str(payload.get(key) or "").strip() for key in ("starts_on", "ends_on", "sport_type")
    )
    return (
        signal_type == "availability"
        and action_type == "record_availability"
        and not has_durable_anchor
        and availability in {"", "available", "unknown"}
        and scope in {"", "day", "general", "week", "planning", "plan", "unknown"}
    )


def _is_planning_availability_constraint_signal(signal: Any) -> bool:
    if str(getattr(signal, "type", "") or "").strip() != "availability":
        return False
    if _signal_action_type(signal) != "record_availability":
        return False
    payload = dict(getattr(signal, "payload", {}) or {})
    return (
        _sport_availability_constraint_from_payload(payload) is not None
        or _availability_window_constraint_from_payload(payload) is not None
    )


def _is_planning_health_metadata_signal(signal: Any) -> bool:
    signal_type = str(getattr(signal, "type", "") or "").strip()
    action_type = _signal_action_type(signal)
    if action_type == "record_health_signal":
        return True
    return signal_type in {"health", "readiness"} and action_type == ""


def _signal_action_type(signal: Any) -> str:
    payload = dict(getattr(signal, "payload", {}) or {})
    explicit = str(payload.get("action_type") or payload.get("type") or "").strip()
    if explicit:
        return explicit
    return {
        "availability": "record_availability",
        "preference": "record_preference",
        "health": "record_health_signal",
        "readiness": "record_health_signal",
    }.get(str(getattr(signal, "type", "") or "").strip(), "")


def _turn_plan_allows_planning(turn_plan: Any) -> bool:
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    secondary = tuple(getattr(turn_plan, "secondary_intents", ()) or ())
    if _turn_plan_has_typed_planning_availability_constraint(turn_plan):
        return _turn_plan_has_explicit_planning_request(turn_plan)
    if primary_intent in _NON_PLANNING_PRIMARY_INTENTS and "plan_mutation" not in secondary:
        return False
    if primary_intent == "plan_mutation":
        return True
    return "plan_mutation" in secondary


def _turn_plan_has_explicit_planning_request(turn_plan: Any) -> bool:
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    secondary = {str(item or "") for item in tuple(getattr(turn_plan, "secondary_intents", ()) or ())}
    planning_action = str(getattr(turn_plan, "planning_action", "") or "").strip()
    if primary_intent == "plan_mutation" or "plan_mutation" in secondary:
        return True
    if bool(getattr(turn_plan, "mutation_signal", False)):
        return True
    return planning_action not in {"", "unknown", "none", "null"}


def _turn_plan_has_typed_planning_availability_constraint(turn_plan: Any) -> bool:
    return (
        _sport_availability_constraint_from_turn_plan(turn_plan) is not None
        or _availability_window_constraint_from_turn_plan(turn_plan) is not None
    )


def _is_session_ref(raw_ref: Any) -> bool:
    return plan_ref_kind(raw_ref) == "session"


def _is_session_role_ref(raw_ref: Any) -> bool:
    return _is_session_ref(raw_ref) or _is_date_like_ref(raw_ref)


def _is_date_like_ref(raw_ref: Any) -> bool:
    return plan_ref_kind(raw_ref) in {"date", "day"}


def _is_sport_window_ref(raw_ref: Any) -> bool:
    value = str(raw_ref or "").strip()
    parts = value.split(":")
    if len(parts) != 4 or parts[0] != "sport_window":
        return False
    return _sport_availability_constraint_from_payload(
        {
            "availability": "unavailable",
            "scope": "sport",
            "sport_type": parts[1],
            "starts_on": parts[2],
            "ends_on": parts[3],
        }
    ) is not None


def _is_availability_window_ref(raw_ref: Any) -> bool:
    value = str(raw_ref or "").strip()
    parts = value.split(":")
    if len(parts) not in {4, 5} or parts[0] != "availability_window":
        return False
    if len(parts) == 4:
        _, scope, starts_on, ends_on = parts
        availability = "unavailable"
    else:
        _, availability, scope, starts_on, ends_on = parts
    return _availability_window_constraint_from_payload(
        {
            "availability": availability,
            "scope": scope,
            "starts_on": starts_on,
            "ends_on": ends_on,
        }
    ) is not None


def _is_iso_date(raw: str) -> bool:
    return is_iso_date(raw)


def _ref_payload(raw: str) -> str:
    return plan_ref_payload(raw)


def _has_active_pending(pending_confirmation: Any) -> bool:
    return pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending"


def _canonical_planning_trace(turn_context: dict[str, object]) -> dict[str, object]:
    trace = turn_context.get("canonical_planning_provider")
    if isinstance(trace, dict):
        return trace
    trace = {
        "source": "coach_understanding",
        "enabled": canonical_planning_provider_enabled(),
        "default_enabled": True,
        "env_value": os.getenv("FITMAS_CANONICAL_PLANNING_PROVIDER"),
        "applicable": None,
        "result": "prepared",
        "fallback_reason": None,
    }
    turn_context["canonical_planning_provider"] = trace
    return trace


def _trace_legacy_skipped(turn_context: dict[str, object]) -> None:
    turn_context["legacy_decide"] = {
        "source": "coach_understanding_planning",
        "ok": True,
        "error_type": None,
        "artifact_kind": "none",
        "response_type": "canonical_planning",
        "decision_present": False,
        "has_plan_patch": False,
        "has_pending_resolution": False,
        "memory_action_count": 0,
        "execution_action_count": 0,
        "decide_none_present": False,
        "legacy_skipped": True,
    }


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
