from __future__ import annotations

from typing import Any

from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.models import Extraction


def compose_canonical_clarification_reply(
    *,
    composer: Any,
    user_text: str,
    turn_plan: Any,
    turn_context: dict[str, object],
    grounding_facts: tuple[str, ...],
) -> ConversationTurnOutcome | None:
    if not _turn_plan_needs_clarification(turn_plan):
        return None
    question = _clarification_question(turn_plan)
    outcome = DecisionOutcome(
        kind="clarification",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Clarification requise",
            reason_summary="Je n'ai pas assez de contexte pour agir proprement.",
            evidence=("turn_plan.needs_clarification",),
            tradeoff=None,
            impact={},
            protected=("no_legacy_decide", "no_uncommitted_plan_claim"),
            next_step=question,
        ),
        reply_contract=ReplyContract(
            mode="canonical_clarification",
            audience="conversation",
            allowed_claims=("clarification",),
            forbidden_claims=("plan_committed", "plan_pending", "execution_updated_without_event"),
        ),
    )
    result = composer.compose(outcome, None, user_text=user_text, grounding_facts=grounding_facts)
    text = str(getattr(result, "text", "") or "").strip()
    if not text:
        turn_context["canonical_clarification"] = {
            "source": "turn_plan",
            "composed": False,
            "reason": getattr(result, "reason", None),
        }
        return None
    turn_context["canonical_clarification"] = {
        "source": "turn_plan",
        "composed": True,
        "verified": bool(getattr(result, "verified", False)),
        "fallback_used": bool(getattr(result, "fallback_used", False)),
    }
    turn_context["legacy_decide"] = {
        "source": "turn_plan_clarification",
        "ok": True,
        "error_type": None,
        "artifact_kind": "none",
        "response_type": "canonical_clarification",
        "decision_present": False,
        "has_plan_patch": False,
        "has_pending_resolution": False,
        "memory_action_count": 0,
        "execution_action_count": 0,
        "decide_none_present": False,
        "legacy_skipped": True,
    }
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=_confidence(turn_plan)),
        reply_text=text,
        response_mode="canonical_clarification",
        decision=None,
        mutation_applied=False,
        pending_confirmation=False,
    )


def _turn_plan_needs_clarification(turn_plan: Any) -> bool:
    if turn_plan is None:
        return False
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    if primary_intent == "needs_clarification":
        return True
    return bool(getattr(turn_plan, "needs_clarification", False))


def _clarification_question(turn_plan: Any) -> str:
    question = str(getattr(turn_plan, "clarification_question", "") or "").strip()
    if question:
        return question
    goal = str(getattr(turn_plan, "user_goal", "") or "").strip()
    if goal:
        return "Tu peux me préciser ce que tu veux faire exactement ?"
    return "Tu peux me préciser ce que tu veux dire ?"


def _confidence(turn_plan: Any) -> float:
    try:
        return max(0.0, min(1.0, float(getattr(turn_plan, "confidence", 0.75) or 0.75)))
    except (TypeError, ValueError):
        return 0.75
