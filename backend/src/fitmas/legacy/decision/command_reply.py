from __future__ import annotations

from typing import Callable

from fitmas.legacy.decision import CoachUnderstanding
from fitmas.legacy.decision.conversation_contract import ConversationTurnOutcome
from fitmas.legacy.decision.message_models import Extraction


def should_compose_understanding_command_reply(action_result: dict | None) -> bool:
    action_result = action_result or {}
    if str(action_result.get("command_source") or "") != "coach_understanding":
        return False
    return any(
        int(action_result.get(key) or 0) > 0
        for key in (
            "memory_applied",
            "memory_blocked",
            "execution_applied",
            "execution_blocked",
            "execution_deferred",
        )
    )


def compose_understanding_command_reply(
    *,
    db,
    user,
    user_text: str,
    understanding: CoachUnderstanding,
    turn_context: dict[str, object],
    grounding,
    action_result: dict,
    compose_no_change_reply_for_turn_fn: Callable[..., tuple[str, str | None]] | None,
) -> ConversationTurnOutcome:
    original_reply = _reply_hint_from_understanding(understanding)
    response_mode = "canonical_command_reply"
    if compose_no_change_reply_for_turn_fn is not None:
        reply_text, composed_mode = compose_no_change_reply_for_turn_fn(
            db=db,
            user=user,
            user_text=user_text,
            original_reply=original_reply,
            turn_context=turn_context,
            grounding=grounding,
            action_result=action_result,
        )
        if composed_mode:
            response_mode = composed_mode
    else:
        reply_text = original_reply
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=understanding.confidence),
        reply_text=reply_text,
        response_mode=response_mode,
        decision=None,
        mutation_applied=False,
    )


def _reply_hint_from_understanding(understanding: CoachUnderstanding) -> str:
    if understanding.user_summary:
        return understanding.user_summary
    if understanding.intent == "execution_report":
        return "Signal d'execution compris."
    if understanding.intent == "pending_response":
        return "Confirmation comprise."
    return "Signal compris."
