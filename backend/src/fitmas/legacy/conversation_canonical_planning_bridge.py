from __future__ import annotations

import os
from datetime import date
from typing import Any, Callable

from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import CoachUnderstanding
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


def canonical_planning_provider_enabled() -> bool:
    return _env_flag_enabled("FITMAS_CANONICAL_PLANNING_PROVIDER", default=False)


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
        turn_context["canonical_planning_provider"] = {
            "intent": understanding.intent,
            "source": "coach_understanding",
            "applicable": False,
            "result": "unsupported_requested_change",
        }
        return None

    turn_context["canonical_planning_provider"] = {
        "intent": understanding.intent,
        "source": "coach_understanding",
        "applicable": True,
    }
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
        turn_context["canonical_planning_provider"]["result"] = "handled"
        turn_context["canonical_planning_provider"]["attempt_reason"] = attempt.reason
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
        turn_context["canonical_planning_provider"]["result"] = "blocked"
        turn_context["canonical_planning_provider"]["attempt_reason"] = attempt.reason
        return planning_runtime_unhandled_outcome(
            reason=attempt.reason,
            user_text=source_text,
            grounding_facts=grounding_facts,
            decision_reply_composer_fn=decision_reply_composer_fn,
        )

    turn_context["canonical_planning_provider"]["result"] = "fallback_legacy"
    turn_context["canonical_planning_provider"]["attempt_reason"] = attempt.reason
    return None


def _requested_change_is_supported(requested_change: Any | None) -> bool:
    if requested_change is None:
        return False
    kind = str(getattr(requested_change, "kind", "") or "").strip()
    if kind not in _SUPPORTED_KINDS:
        return False
    source_ref = getattr(requested_change, "source_ref", None)
    target_ref = getattr(requested_change, "target_ref", None)
    if kind == "move":
        return _is_session_ref(source_ref) and _is_date_like_ref(target_ref)
    if kind == "swap":
        return _is_session_ref(source_ref) and _is_session_ref(target_ref)
    if kind in {"lighten", "replace"}:
        return _is_session_ref(source_ref)
    if kind == "create":
        return _is_date_like_ref(target_ref) and bool(str(getattr(requested_change, "desired_sport", "") or "").strip())
    return False


def _has_blocking_command_signals(understanding: CoachUnderstanding) -> bool:
    commands = commands_from_understanding(understanding).commands
    if not commands:
        return False
    if all(_is_planning_preference_metadata_signal(signal) for signal in understanding.extracted_signals):
        return False
    return True


def _is_planning_preference_metadata_signal(signal: Any) -> bool:
    payload = dict(getattr(signal, "payload", {}) or {})
    action_type = str(payload.get("action_type") or payload.get("type") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    signal_type = str(getattr(signal, "type", "") or "").strip()
    return signal_type == "preference" and action_type == "record_preference" and scope in {
        "session",
        "planning",
        "plan",
    }


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
    if not raw.startswith("session_id:"):
        return False
    try:
        return int(raw.split(":", 1)[1]) > 0
    except (IndexError, TypeError, ValueError):
        return False


def _is_date_like_ref(raw_ref: Any) -> bool:
    raw = str(raw_ref or "").strip()
    if raw.startswith("date:"):
        try:
            date.fromisoformat(raw.split(":", 1)[1][:10])
        except (IndexError, ValueError):
            return False
        return True
    if raw.startswith("day:"):
        return bool(raw.split(":", 1)[1].strip())
    return False


def _has_active_pending(pending_confirmation: Any) -> bool:
    return pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending"


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
