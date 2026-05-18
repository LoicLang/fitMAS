from __future__ import annotations

import os
from datetime import date
from typing import Any, Callable

from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import CoachUnderstanding, RequestedPlanChange
from fitmas.legacy.coach_command_adapter import commands_from_understanding
from fitmas.legacy.conversation_planning_bridge import (
    conversation_outcome_from_planning_runtime_result,
    planning_runtime_unhandled_outcome,
)
from fitmas.legacy.planning_runtime_adapter import run_planning_runtime_attempt_from_understanding

_SUPPORTED_KINDS = {"move", "swap", "lighten", "replace", "create"}
_NON_PLANNING_PRIMARY_INTENTS = {
    "availability_constraint",
    "close_turn",
    "execution_report",
    "health_signal",
    "plan_lookup",
}
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


def planning_understanding_for_provider(
    *,
    understanding: CoachUnderstanding | None,
    turn_plan: Any,
) -> CoachUnderstanding | None:
    if understanding is not None and understanding.intent == "plan_change" and understanding.requested_change is not None:
        if _has_blocking_command_signals(understanding) or _requested_change_is_supported(understanding.requested_change):
            return understanding
    if not _turn_plan_allows_planning(turn_plan):
        return understanding
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
                "result": "fallback_legacy",
                "fallback_reason": "unsupported_requested_change",
            }
        )
        return None

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
        return planning_runtime_unhandled_outcome(
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
    else:
        return None
    return RequestedPlanChange(
        kind=kind,
        source_ref=source_ref,
        target_ref=target_ref,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason=str(getattr(turn_plan, "user_goal", "") or "Demande planning typee par TurnPlan.").strip(),
        risk_signals=(),
    )


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
        return _is_session_role_ref(source_ref)
    if kind == "create":
        return _is_date_like_ref(target_ref) and bool(str(getattr(requested_change, "desired_sport", "") or "").strip())
    return False


def _has_blocking_command_signals(understanding: CoachUnderstanding) -> bool:
    commands = commands_from_understanding(understanding).commands
    if not commands:
        return False
    if all(_is_nonblocking_planning_sidecar_signal(signal) for signal in understanding.extracted_signals):
        return False
    return True


def _is_nonblocking_planning_sidecar_signal(signal: Any) -> bool:
    return _is_planning_preference_metadata_signal(signal) or _is_planning_availability_metadata_signal(signal)


def _is_planning_preference_metadata_signal(signal: Any) -> bool:
    payload = dict(getattr(signal, "payload", {}) or {})
    action_type = str(payload.get("action_type") or payload.get("type") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    signal_type = str(getattr(signal, "type", "") or "").strip()
    return signal_type == "preference" and action_type == "record_preference" and scope in {
        "day",
        "general",
        "session",
        "week",
        "planning",
        "plan",
    }


def _is_planning_availability_metadata_signal(signal: Any) -> bool:
    payload = dict(getattr(signal, "payload", {}) or {})
    action_type = str(payload.get("action_type") or payload.get("type") or "").strip()
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


def _turn_plan_allows_planning(turn_plan: Any) -> bool:
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    if primary_intent in _NON_PLANNING_PRIMARY_INTENTS:
        return False
    if primary_intent == "plan_mutation":
        return True
    secondary = tuple(getattr(turn_plan, "secondary_intents", ()) or ())
    return "plan_mutation" in secondary


def _is_session_ref(raw_ref: Any) -> bool:
    raw = str(raw_ref or "").strip()
    if not raw.startswith(("session_id:", "session_", "session:")):
        return False
    try:
        return int(_ref_payload(raw)) > 0
    except (IndexError, TypeError, ValueError):
        return False


def _is_session_role_ref(raw_ref: Any) -> bool:
    return _is_session_ref(raw_ref) or _is_date_like_ref(raw_ref)


def _is_date_like_ref(raw_ref: Any) -> bool:
    raw = str(raw_ref or "").strip()
    if raw.startswith(("date:", "date_")):
        try:
            date.fromisoformat(_ref_payload(raw)[:10])
        except (IndexError, ValueError):
            return False
        return True
    if _is_iso_date(raw):
        return True
    if raw.startswith("day:"):
        return bool(raw.split(":", 1)[1].strip())
    return False


def _is_iso_date(raw: str) -> bool:
    if len(raw) < 10:
        return False
    if len(raw) > 10 and raw[10] not in {"T", " "}:
        return False
    try:
        date.fromisoformat(raw[:10])
    except ValueError:
        return False
    return True


def _ref_payload(raw: str) -> str:
    if ":" in raw:
        return raw.split(":", 1)[1].strip()
    if "_" in raw:
        return raw.split("_", 1)[1].strip()
    return raw


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
