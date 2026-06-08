from __future__ import annotations

from fitmas.legacy.decision.conversation_contract import ConversationTurnOutcome, ConversationTurnState
from fitmas.legacy.decision import activity_highlight
from fitmas.legacy.decision import clarification_reply


def route_pre_understanding_replies(
    *,
    user_text: str,
    turn_plan,
    state: ConversationTurnState,
    turn_context: dict[str, object],
    grounding_facts,
    decision_reply_composer_fn,
) -> ConversationTurnOutcome | None:
    clarification_outcome = clarification_reply.compose_canonical_clarification_reply(
        composer=decision_reply_composer_fn(),
        user_text=user_text,
        turn_plan=turn_plan,
        turn_context=turn_context,
        grounding_facts=grounding_facts,
    )
    if clarification_outcome is not None:
        return clarification_outcome

    return activity_highlight.compose_activity_highlight_reply(
        composer=decision_reply_composer_fn(),
        activities=tuple(state.activities),
        user_text=user_text,
        turn_plan=turn_plan,
        turn_context=turn_context,
        grounding_facts=grounding_facts,
    )
