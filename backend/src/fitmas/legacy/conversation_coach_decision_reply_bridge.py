from __future__ import annotations

from typing import Any, Callable

from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.models import Extraction
from fitmas.legacy import conversation_readonly_reply_bridge


def can_route_coach_decision_reply(
    *,
    decision_artifact: Any,
    turn_context: dict[str, object],
    action_result: dict | None = None,
) -> bool:
    response_mode = str(getattr(decision_artifact, "response_type", "reply") or "reply")
    action_result = action_result or {}
    if int(action_result.get("execution_applied") or 0) > 0:
        return True
    return response_mode in {"no_change", "reply"}


def should_compose_coach_decision_reply(
    *,
    decision_artifact: Any,
    turn_context: dict[str, object],
    action_result: dict | None = None,
) -> bool:
    response_mode = str(getattr(decision_artifact, "response_type", "reply") or "reply")
    primary_intent = conversation_readonly_reply_bridge.turn_context_primary_intent(turn_context)
    action_result = action_result or {}
    if int(action_result.get("execution_applied") or 0) > 0:
        return True
    return response_mode == "no_change" or (
        response_mode == "reply" and primary_intent == "execution_report"
    )


def compose_coach_decision_reply(
    *,
    db,
    user,
    user_text: str,
    decision_artifact: Any,
    turn_context: dict[str, object],
    grounding,
    action_result: dict,
    compose_no_change_reply_for_turn_fn: Callable[..., tuple[str, str | None]] | None,
) -> ConversationTurnOutcome:
    reply_text = str(getattr(decision_artifact, "confirmation_reason", None) or getattr(decision_artifact, "reply_hint", ""))
    response_mode = str(getattr(decision_artifact, "response_type", "reply") or "reply")
    if (
        should_compose_coach_decision_reply(
            decision_artifact=decision_artifact,
            turn_context=turn_context,
            action_result=action_result,
        )
        and compose_no_change_reply_for_turn_fn is not None
    ):
        reply_text, composed_mode = compose_no_change_reply_for_turn_fn(
            db=db,
            user=user,
            user_text=user_text,
            original_reply=reply_text,
            turn_context=turn_context,
            grounding=grounding,
            action_result=action_result,
        )
        if composed_mode:
            response_mode = composed_mode
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=reply_text,
        response_mode=response_mode,
        decision=None,
        mutation_applied=False,
    )
