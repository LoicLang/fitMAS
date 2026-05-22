from __future__ import annotations

from sqlalchemy.orm import Session

import fitmas.llm.gateway as gw
import fitmas.llm.reply_backend as final_reply
import fitmas.decision.turn_close_route as turn_close_route
import fitmas.decision.turn_pending_route as turn_pending_route
import fitmas.decision.turn_planning_route as turn_planning_route
import fitmas.decision.turn_pre_understanding_reply_route as turn_pre_understanding_reply_route
import fitmas.decision.turn_understanding_route as turn_understanding_route
from fitmas.decision.conversation_contract import (
    ConversationPipelineDependencies,
    ConversationTurnInput,
    ConversationTurnState,
)
from fitmas.decision import DecisionReplyComposer
from fitmas.decision import turn_context as turn_context_builder
from fitmas.decision import turn_finalization
from fitmas.decision.message_models import MessageReply
from fitmas.llm.reply_decision_backend import LLMReplyBackend

def route_conversation_turn(
    *,
    db: Session,
    user,
    payload: ConversationTurnInput,
    dependencies: ConversationPipelineDependencies,
    state: ConversationTurnState,
    pending_confirmation,
    open_calibration_need,
    context_artifacts: turn_context_builder.TurnContextArtifacts,
    turn_memory_writes: list[dict],
) -> MessageReply:
    conversation_context = context_artifacts.conversation_context
    coach_bundle = context_artifacts.coach_bundle
    turn_plan = context_artifacts.turn_plan
    unresolved_execution_followup_text = context_artifacts.unresolved_execution_followup_text
    grounding_packet = context_artifacts.grounding_packet
    grounding_facts = context_artifacts.grounding_facts
    turn_context = context_artifacts.turn_context

    close_outcome = turn_close_route.compose_terminal_close_outcome(
        user_text=payload.text,
        previous_agent_text=state.previous_agent_text,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
        open_calibration_need=open_calibration_need,
        grounding=grounding_packet,
        turn_context=turn_context,
        reply_backend=final_reply,
    )
    if close_outcome is not None:
        return turn_finalization.record_turn_outcome(
            db=db,
            user=user,
            payload=payload,
            outcome=close_outcome,
            turn_context=turn_context,
            turn_memory_writes=turn_memory_writes,
        )

    pending_route = turn_pending_route.route_pending_confirmation(
        db=db,
        user=user,
        user_text=payload.text,
        turn_plan=turn_plan,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
        state=state,
        pending_confirmation=pending_confirmation,
        turn_context=turn_context,
    )
    canonical_understanding = pending_route.canonical_understanding
    if pending_route.outcome is not None:
        return turn_finalization.record_turn_outcome(
            db=db,
            user=user,
            payload=payload,
            outcome=pending_route.outcome,
            turn_context=turn_context,
            turn_memory_writes=turn_memory_writes,
        )

    pre_understanding_reply_outcome = turn_pre_understanding_reply_route.route_pre_understanding_replies(
        user_text=payload.text,
        turn_plan=turn_plan,
        state=state,
        turn_context=turn_context,
        grounding_facts=grounding_facts,
        decision_reply_composer_fn=_decision_reply_composer,
    )
    if pre_understanding_reply_outcome is not None:
        return turn_finalization.record_turn_outcome(
            db=db,
            user=user,
            payload=payload,
            outcome=pre_understanding_reply_outcome,
            turn_context=turn_context,
            turn_memory_writes=turn_memory_writes,
        )

    planning_route = turn_planning_route.route_pre_understanding_planning(
        db=db,
        user=user,
        user_text=payload.text,
        turn_plan=turn_plan,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
        state=state,
        pending_confirmation=pending_confirmation,
        context_artifacts=context_artifacts,
        grounding_facts=grounding_facts,
        turn_context=turn_context,
        decision_reply_composer_fn=_decision_reply_composer,
        reviewer_request_json_fn=gw.request_json,
    )
    if planning_route.understanding_refreshed:
        canonical_understanding = planning_route.canonical_understanding
    if planning_route.outcome is not None:
        if planning_route.apply_turn_plan_memory_commands:
            turn_planning_route.apply_turn_plan_memory_commands_once(
                db=db,
                user=user,
                turn_plan=turn_plan,
                turn_memory_writes=turn_memory_writes,
                turn_context=turn_context,
            )
        return turn_finalization.record_turn_outcome(
            db=db,
            user=user,
            payload=payload,
            outcome=planning_route.outcome,
            turn_context=turn_context,
            turn_memory_writes=turn_memory_writes,
        )

    outcome = turn_understanding_route.route_post_pre_understanding_decision(
        db=db,
        user=user,
        user_text=payload.text,
        turn_plan=turn_plan,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
        state=state,
        pending_confirmation=pending_confirmation,
        context_artifacts=context_artifacts,
        grounding_packet=grounding_packet,
        grounding_facts=grounding_facts,
        turn_context=turn_context,
        turn_memory_writes=turn_memory_writes,
        canonical_understanding=canonical_understanding,
        unresolved_execution_followup_text=unresolved_execution_followup_text,
        decision_reply_composer_fn=_decision_reply_composer,
        reviewer_request_json_fn=gw.request_json,
    )

    return turn_finalization.finalize_and_record_outcome(
        db=db,
        user=user,
        payload=payload,
        outcome=outcome,
        state=state,
        dependencies=dependencies,
        pending_confirmation=pending_confirmation,
        turn_context=turn_context,
        turn_memory_writes=turn_memory_writes,
    )


def _decision_reply_composer() -> DecisionReplyComposer:
    return DecisionReplyComposer(reply_backend=LLMReplyBackend())
