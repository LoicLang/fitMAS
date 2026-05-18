from __future__ import annotations

import os
from typing import Any

from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import CoachUnderstanding, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.legacy.coach_command_adapter import commands_from_understanding
from fitmas.models import Extraction

_READONLY_INTENTS = {
    "answer",
    "general_answer",
    "plan_lookup",
    "fact_recall",
}
_NON_READONLY_INTENTS = {
    "availability_signal",
    "clarification",
    "close",
    "execution_report",
    "health_signal",
    "memory_update",
    "pending_response",
    "plan_change",
}
_NON_READONLY_PRIMARY_INTENTS = {
    "availability_constraint",
    "close_turn",
    "execution_report",
    "health_signal",
    "plan_mutation",
}


def canonical_readonly_provider_enabled() -> bool:
    return _env_flag_enabled("FITMAS_CANONICAL_READONLY_PROVIDER", default=True)


def should_use_canonical_readonly_without_legacy(
    *,
    understanding: CoachUnderstanding | None,
    turn_plan: Any,
    pending_confirmation: Any,
) -> bool:
    if not canonical_readonly_provider_enabled():
        return False
    if understanding is None:
        return False
    if _turn_plan_has_non_readonly_primary_intent(turn_plan):
        return False
    if understanding.intent in _NON_READONLY_INTENTS:
        return False
    if understanding.intent == "plan_change" or understanding.requested_change is not None:
        return False
    if understanding.pending_resolution is not None or _has_active_pending(pending_confirmation):
        return False
    if commands_from_understanding(understanding).commands:
        return False
    return _turn_plan_is_readonly_answer(turn_plan) or understanding.intent in _READONLY_INTENTS


def compose_canonical_readonly_reply(
    *,
    composer,
    understanding: CoachUnderstanding,
    user_text: str,
    turn_plan: Any,
    turn_context: dict[str, object],
    grounding_facts: tuple[str, ...],
) -> ConversationTurnOutcome | None:
    outcome = _answer_outcome_from_understanding(understanding, turn_plan=turn_plan)
    result = composer.compose(
        outcome,
        None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    if result is None or not getattr(result, "text", None):
        turn_context["canonical_readonly_reply"] = {
            "intent": understanding.intent,
            "source": "coach_understanding",
            "composed": False,
            "reason": getattr(result, "reason", None) if result is not None else "empty",
        }
        return None

    turn_context["canonical_readonly_reply"] = {
        "intent": understanding.intent,
        "source": "coach_understanding",
        "composed": True,
        "verified": bool(getattr(result, "verified", False)),
        "fallback_used": bool(getattr(result, "fallback_used", False)),
    }
    turn_context["legacy_decide"] = {
        "source": "coach_understanding_readonly",
        "ok": True,
        "error_type": None,
        "artifact_kind": "none",
        "response_type": "canonical_readonly_answer",
        "decision_present": False,
        "has_plan_patch": False,
        "has_pending_resolution": False,
        "memory_action_count": 0,
        "execution_action_count": 0,
        "decide_none_present": False,
        "legacy_skipped": True,
    }
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=understanding.confidence),
        reply_text=str(result.text),
        response_mode="canonical_readonly_answer",
        decision=None,
        mutation_applied=False,
    )


def _answer_outcome_from_understanding(
    understanding: CoachUnderstanding,
    *,
    turn_plan: Any,
) -> DecisionOutcome:
    reason = understanding.user_summary or "Reponse basee sur le contexte disponible."
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    return DecisionOutcome(
        kind="answer",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label=primary_intent or understanding.intent or "answer",
            reason_summary=reason,
            evidence=(),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="canonical_readonly_answer",
            audience="user",
            allowed_claims=("read_truth", "answer"),
            forbidden_claims=("mutation_committed", "pending_created", "plan_changed"),
        ),
    )


def _turn_plan_is_readonly_answer(turn_plan: Any) -> bool:
    if turn_plan is None:
        return False
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    if primary_intent in _NON_READONLY_PRIMARY_INTENTS:
        return False
    if primary_intent in _READONLY_INTENTS:
        return True
    if bool(getattr(turn_plan, "requires_truth_read", False)):
        return True
    return str(getattr(turn_plan, "truth_scope", "") or "") in {"plan_window", "facts", "memory"}


def _turn_plan_has_non_readonly_primary_intent(turn_plan: Any) -> bool:
    if turn_plan is None:
        return False
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    return primary_intent in _NON_READONLY_PRIMARY_INTENTS


def _has_active_pending(pending_confirmation: Any) -> bool:
    return pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending"


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
