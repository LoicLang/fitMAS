from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

import fitmas.llm.gateway as gw
import fitmas.llm.reply_backend as final_reply
from fitmas.conversation_contract import (
    ConversationPipelineDependencies,
    ConversationTurnInput,
    ConversationTurnOutcome,
    ConversationTurnState,
)
from fitmas.decision import DecisionReplyComposer
from fitmas.decision import activity_highlight
from fitmas.decision import clarification_reply
from fitmas.decision import coach_decision_runtime
from fitmas.decision import command_application
from fitmas.decision import pending_resolution
from fitmas.decision import planning_runtime
from fitmas.decision import readonly_reply
from fitmas.decision import turn_context as turn_context_builder
from fitmas.decision import turn_finalization
from fitmas.decision import turn_idempotency
from fitmas.decision import understanding_runtime
from fitmas.llm.reply_decision_backend import LLMReplyBackend
from fitmas.models import Extraction, MessageReply


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

    if turn_context_builder.should_use_terminal_close_path(
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
        open_calibration_need=open_calibration_need,
    ):
        composed_close_reply = final_reply.compose_close_turn_reply(
            user_text=payload.text,
            previous_agent_text=state.previous_agent_text,
            grounding=grounding_packet,
        )
        close_reply_source = "composer" if composed_close_reply else "outage_fallback"
        reply_text = composed_close_reply or final_reply.close_turn_outage_fallback_reply()
        turn_context.update(
            {
                "terminal_close": True,
                "tools_offered": 0,
                "open_question_marker": "suppressed",
                "close_turn_reply_source": close_reply_source,
            }
        )
        return turn_finalization.record_turn_reply(
            db=db,
            user=user,
            payload=payload,
            reply_text=reply_text,
            extraction=Extraction(confidence=float(getattr(turn_plan, "confidence", 0.95) or 0.95)),
            response_mode="close_turn_composed",
            turn_context=turn_context,
            turn_memory_writes=turn_memory_writes,
        )

    canonical_understanding = None
    if pending_resolution.should_prepare_canonical_pending_understanding(
        pending_confirmation=pending_confirmation,
    ):
        turn_context["canonical_pending_provider"] = {
            "active_pending_id": getattr(pending_confirmation, "id", None),
            "source": "coach_understanding",
            "result": "prepared",
        }
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
            turn_context["canonical_pending_provider"]["result"] = "handled"
            return turn_finalization.record_turn_outcome(
                db=db,
                user=user,
                payload=payload,
                outcome=pending_outcome,
                turn_context=turn_context,
                turn_memory_writes=turn_memory_writes,
            )
        turn_context["canonical_pending_provider"]["result"] = (
            "no_pending_resolution" if canonical_understanding is None else "fallback_legacy"
        )

    canonical_clarification_outcome = clarification_reply.compose_canonical_clarification_reply(
        composer=_decision_reply_composer(),
        user_text=payload.text,
        turn_plan=turn_plan,
        turn_context=turn_context,
        grounding_facts=grounding_facts,
    )
    if canonical_clarification_outcome is not None:
        return turn_finalization.record_turn_outcome(
            db=db,
            user=user,
            payload=payload,
            outcome=canonical_clarification_outcome,
            turn_context=turn_context,
            turn_memory_writes=turn_memory_writes,
        )

    if planning_runtime.should_prepare_canonical_planning_understanding(
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
    ):
        planning_runtime.trace_canonical_planning_prepared(
            turn_context,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
        )
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
        planning_understanding = planning_runtime.planning_understanding_for_provider(
            understanding=canonical_understanding,
            turn_plan=turn_plan,
        )
        if planning_understanding is not canonical_understanding:
            turn_context["canonical_planning_provider"]["understanding_source"] = "turn_plan"
        if planning_runtime.should_use_canonical_planning_without_legacy(
            understanding=planning_understanding,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
        ):
            canonical_planning_outcome = planning_runtime.handle_canonical_planning(
                understanding=planning_understanding,
                context=turn_context_builder.planning_context_from_artifacts(context_artifacts),
                db=db,
                user=user,
                source_text=payload.text,
                coach_state_bundle=coach_bundle,
                reviewer_request_json_fn=gw.request_json,
                grounding_facts=grounding_facts,
                decision_reply_composer_fn=_decision_reply_composer,
                turn_context=turn_context,
            )
            if canonical_planning_outcome is not None:
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
                    outcome=canonical_planning_outcome,
                    turn_context=turn_context,
                    turn_memory_writes=turn_memory_writes,
                )
        else:
            if planning_runtime.should_handle_unsupported_canonical_planning_without_legacy(
                understanding=planning_understanding,
                turn_plan=turn_plan,
                pending_confirmation=pending_confirmation,
            ):
                canonical_planning_outcome = planning_runtime.handle_canonical_planning(
                    understanding=planning_understanding,
                    context=turn_context_builder.planning_context_from_artifacts(context_artifacts),
                    db=db,
                    user=user,
                    source_text=payload.text,
                    coach_state_bundle=coach_bundle,
                    reviewer_request_json_fn=gw.request_json,
                    grounding_facts=grounding_facts,
                    decision_reply_composer_fn=_decision_reply_composer,
                    turn_context=turn_context,
                )
                if canonical_planning_outcome is not None:
                    return turn_finalization.record_turn_outcome(
                        db=db,
                        user=user,
                        payload=payload,
                        outcome=canonical_planning_outcome,
                        turn_context=turn_context,
                        turn_memory_writes=turn_memory_writes,
                    )
            else:
                planning_runtime.trace_canonical_planning_not_used(
                    turn_context,
                    understanding=planning_understanding,
                    turn_plan=turn_plan,
                    pending_confirmation=pending_confirmation,
                )

    activity_highlight_outcome = activity_highlight.compose_activity_highlight_reply(
        composer=_decision_reply_composer(),
        activities=tuple(state.activities),
        user_text=payload.text,
        turn_plan=turn_plan,
        turn_context=turn_context,
        grounding_facts=grounding_facts,
    )
    if activity_highlight_outcome is not None:
        return turn_finalization.record_turn_outcome(
            db=db,
            user=user,
            payload=payload,
            outcome=activity_highlight_outcome,
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
    outcome: ConversationTurnOutcome | None = None
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
            understanding_action_result = _apply_understanding_commands(
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
            planning_understanding = planning_runtime.planning_understanding_for_provider(
                understanding=canonical_understanding,
                turn_plan=turn_plan,
            )
            if planning_understanding is not canonical_understanding:
                turn_context.setdefault("canonical_planning_provider", {})["understanding_source"] = "turn_plan"
            if planning_runtime.should_use_canonical_planning_without_legacy(
                understanding=planning_understanding,
                turn_plan=turn_plan,
                pending_confirmation=pending_confirmation,
            ):
                outcome = planning_runtime.handle_canonical_planning(
                    understanding=planning_understanding,
                    context=turn_context_builder.planning_context_from_artifacts(context_artifacts),
                    db=db,
                    user=user,
                    source_text=payload.text,
                    coach_state_bundle=coach_bundle,
                    reviewer_request_json_fn=gw.request_json,
                    grounding_facts=grounding_facts,
                    decision_reply_composer_fn=_decision_reply_composer,
                    turn_context=turn_context,
                )
                if outcome is not None:
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


def _apply_understanding_commands(
    *,
    db: Session,
    user,
    understanding,
    turn_memory_writes: list[dict],
    unresolved_execution_followup: str | None = None,
) -> dict[str, Any]:
    return command_application.apply_understanding_commands(
        db=db,
        user=user,
        understanding=understanding,
        turn_memory_writes=turn_memory_writes,
        unresolved_execution_followup=unresolved_execution_followup,
    )
