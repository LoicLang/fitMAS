from __future__ import annotations

from fitmas.legacy.decision.conversation_contract import ConversationTurnOutcome
from fitmas.legacy.decision.message_models import Extraction
from fitmas.legacy.decision import turn_context as turn_context_builder


def compose_terminal_close_outcome(
    *,
    user_text: str,
    previous_agent_text: str | None,
    turn_plan,
    pending_confirmation,
    open_calibration_need,
    grounding,
    turn_context: dict[str, object],
    reply_backend,
) -> ConversationTurnOutcome | None:
    if not turn_context_builder.should_use_terminal_close_path(
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
        open_calibration_need=open_calibration_need,
    ):
        return None

    composed_close_reply = reply_backend.compose_close_turn_reply(
        user_text=user_text,
        previous_agent_text=previous_agent_text,
        grounding=grounding,
    )
    close_reply_source = "composer" if composed_close_reply else "outage_fallback"
    reply_text = composed_close_reply or reply_backend.close_turn_outage_fallback_reply()
    turn_context.update(
        {
            "terminal_close": True,
            "tools_offered": 0,
            "open_question_marker": "suppressed",
            "close_turn_reply_source": close_reply_source,
        }
    )
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=float(getattr(turn_plan, "confidence", 0.95) or 0.95)),
        reply_text=reply_text,
        response_mode="close_turn_composed",
    )
