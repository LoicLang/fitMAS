from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

import fitmas.llm.gateway as gw
import fitmas.llm.reply_backend as final_reply
import fitmas.decision.turn_close_route as turn_close_route
import fitmas.decision.turn_pending_route as turn_pending_route
import fitmas.decision.turn_planning_route as turn_planning_route
import fitmas.decision.turn_pre_understanding_reply_route as turn_pre_understanding_reply_route
from fitmas.decision.conversation_contract import (
    ConversationPipelineDependencies,
    ConversationTurnInput,
    ConversationTurnState,
)
from fitmas.decision import DecisionReplyComposer
from fitmas.decision import coach_decision_runtime
from fitmas.decision import command_application
from fitmas.decision import pending_resolution
from fitmas.decision import readonly_reply
from fitmas.decision import turn_context as turn_context_builder
from fitmas.decision import turn_finalization
from fitmas.decision import turn_idempotency
from fitmas.decision import understanding_runtime
from fitmas.decision.message_models import Extraction, MessageReply
from fitmas.llm.reply_decision_backend import LLMReplyBackend

logger = logging.getLogger(__name__)

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
            _apply_turn_plan_memory_commands_once(
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

    if canonical_understanding is None:
        canonical_understanding = understanding_runtime.run_canonical_understanding_shadow(
            user=user,
            user_text=payload.text,
            turn_plan=turn_plan,
            conversation_context=conversation_context,
            coach_bundle=coach_bundle,
            state=state,
            pending_confirmation=pending_confirmation,
            turn_context=turn_context,
        )
    outcome = None
    understanding_action_result: dict[str, Any] | None = None
    if understanding_runtime.should_use_canonical_understanding_without_legacy(
        understanding=canonical_understanding,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
    ):
        turn_context["legacy_decide"] = understanding_runtime.trace_canonical_understanding_pivot(
            canonical_understanding,
            turn_plan=turn_plan,
        )
        if turn_idempotency.turn_is_obsolete(db=db, user=user, turn_context=turn_context):
            outcome = turn_idempotency.obsolete_turn_outcome(turn_context=turn_context)
        else:
            understanding_action_result = command_application.apply_understanding_commands(
                db=db,
                user=user,
                understanding=canonical_understanding,
                turn_memory_writes=turn_memory_writes,
                unresolved_execution_followup=unresolved_execution_followup_text,
            )
            turn_context["understanding_command_result"] = understanding_action_result
    else:
        if readonly_reply.should_use_canonical_readonly_without_legacy(
            understanding=canonical_understanding,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
        ):
            outcome = readonly_reply.compose_canonical_readonly_reply(
                composer=DecisionReplyComposer(reply_backend=LLMReplyBackend()),
                understanding=canonical_understanding,
                user_text=payload.text,
                turn_plan=turn_plan,
                turn_context=turn_context,
                grounding_facts=grounding_facts,
            )
        if outcome is None:
            planning_route = turn_planning_route.route_with_existing_understanding(
                db=db,
                user=user,
                user_text=payload.text,
                understanding=canonical_understanding,
                turn_plan=turn_plan,
                pending_confirmation=pending_confirmation,
                context_artifacts=context_artifacts,
                coach_bundle=coach_bundle,
                grounding_facts=grounding_facts,
                turn_context=turn_context,
                decision_reply_composer_fn=_decision_reply_composer,
                reviewer_request_json_fn=gw.request_json,
            )
            outcome = planning_route.outcome
            if outcome is not None and planning_route.apply_turn_plan_memory_commands:
                _apply_turn_plan_memory_commands_once(
                    db=db,
                    user=user,
                    turn_plan=turn_plan,
                    turn_memory_writes=turn_memory_writes,
                    turn_context=turn_context,
                )
        if outcome is None:
            legacy_skip_reason = coach_decision_runtime.legacy_provider_skip_reason(turn_context)
            coach_decision_runtime.trace_legacy_provider_skipped(turn_context, reason=legacy_skip_reason)
            outcome = coach_decision_runtime.canonical_provider_clarification_outcome(
                reason=legacy_skip_reason,
                user_text=payload.text,
                grounding_facts=grounding_facts,
                decision_reply_composer_fn=_decision_reply_composer,
            )

    if outcome is None:
        pending_outcome = pending_resolution.apply_pending_resolution(
            db=db,
            user=user,
            decision_artifact=None,
            canonical_understanding=canonical_understanding,
            pending_confirmation=pending_confirmation,
            user_text=payload.text,
            turn_plan=turn_plan,
        )
        if pending_outcome is not None:
            outcome = pending_outcome

    if (
        outcome is None
        and canonical_understanding is not None
        and readonly_reply.should_compose_understanding_command_reply(
            understanding_action_result,
        )
    ):
        outcome = readonly_reply.compose_understanding_command_reply(
            db=db,
            user=user,
            user_text=payload.text,
            understanding=canonical_understanding,
            turn_context=turn_context,
            grounding=grounding_packet,
            action_result=understanding_action_result or {},
            compose_no_change_reply_for_turn_fn=readonly_reply.compose_no_change_reply_for_turn,
        )
    if outcome is None:
        decide_none_context = coach_decision_runtime.decide_none_context(turn_context)
        turn_context["decide_none"] = decide_none_context

    if outcome is None:
        logger.warning("conversation_router: decide() returned None with no fallback decision")
        turn_context.setdefault("decide_none", coach_decision_runtime.decide_none_context(turn_context))
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=0.5),
            reply_text="Je ne peux pas te repondre tout de suite. Reessaie dans un instant.",
            response_mode="llm_unavailable",
        )

    pending_resolution.keep_pending_for_non_mutating_turn(
        outcome=outcome,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
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

def _apply_turn_plan_memory_commands_once(
    *,
    db: Session,
    user,
    turn_plan,
    turn_memory_writes: list[dict],
    turn_context: dict[str, object],
) -> None:
    if "turn_plan_memory_action_result" in turn_context:
        return
    command_application.apply_turn_plan_memory_commands(
        db=db,
        user=user,
        turn_plan=turn_plan,
        turn_memory_writes=turn_memory_writes,
        turn_context=turn_context,
    )
