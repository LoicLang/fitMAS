from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

from fitmas.decision.conversation_contract import ConversationTurnOutcome, ConversationTurnState
from fitmas.decision.message_models import Extraction
from fitmas.decision import coach_decision_runtime
from fitmas.decision import command_application
from fitmas.decision import pending_resolution
from fitmas.decision import readonly_reply
from fitmas.decision import turn_context as turn_context_builder
from fitmas.decision import turn_idempotency
from fitmas.decision import turn_planning_route
from fitmas.decision import understanding_runtime


logger = logging.getLogger(__name__)


def route_post_pre_understanding_decision(
    *,
    db: Session,
    user: Any,
    user_text: str,
    turn_plan: Any,
    conversation_context: Any,
    coach_bundle: Any,
    state: ConversationTurnState,
    pending_confirmation: Any,
    context_artifacts: turn_context_builder.TurnContextArtifacts,
    grounding_packet: dict[str, object],
    grounding_facts: tuple[str, ...],
    turn_context: dict[str, object],
    turn_memory_writes: list[dict],
    canonical_understanding: Any | None,
    unresolved_execution_followup_text: str | None,
    decision_reply_composer_fn: Callable[[], Any],
    reviewer_request_json_fn: Callable[..., Any],
) -> ConversationTurnOutcome:
    if canonical_understanding is None:
        canonical_understanding = understanding_runtime.run_canonical_understanding_shadow(
            user=user,
            user_text=user_text,
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
            understanding_action_result = command_application.apply_understanding_commands(
                db=db,
                user=user,
                understanding=canonical_understanding,
                turn_memory_writes=turn_memory_writes,
                unresolved_execution_followup=unresolved_execution_followup_text,
            )
            turn_context["understanding_command_result"] = understanding_action_result
    else:
        outcome = _route_readonly_planning_or_provider_clarification(
            db=db,
            user=user,
            user_text=user_text,
            understanding=canonical_understanding,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
            context_artifacts=context_artifacts,
            coach_bundle=coach_bundle,
            grounding_facts=grounding_facts,
            turn_context=turn_context,
            turn_memory_writes=turn_memory_writes,
            decision_reply_composer_fn=decision_reply_composer_fn,
            reviewer_request_json_fn=reviewer_request_json_fn,
        )

    if outcome is None:
        outcome = _route_pending_or_command_reply(
            db=db,
            user=user,
            user_text=user_text,
            understanding=canonical_understanding,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
            grounding_packet=grounding_packet,
            turn_context=turn_context,
            understanding_action_result=understanding_action_result,
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
    return outcome


def _route_readonly_planning_or_provider_clarification(
    *,
    db: Session,
    user: Any,
    user_text: str,
    understanding: Any,
    turn_plan: Any,
    pending_confirmation: Any,
    context_artifacts: turn_context_builder.TurnContextArtifacts,
    coach_bundle: Any,
    grounding_facts: tuple[str, ...],
    turn_context: dict[str, object],
    turn_memory_writes: list[dict],
    decision_reply_composer_fn: Callable[[], Any],
    reviewer_request_json_fn: Callable[..., Any],
) -> ConversationTurnOutcome | None:
    if readonly_reply.should_use_canonical_readonly_without_legacy(
        understanding=understanding,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
    ):
        outcome = readonly_reply.compose_canonical_readonly_reply(
            composer=decision_reply_composer_fn(),
            understanding=understanding,
            user_text=user_text,
            turn_plan=turn_plan,
            turn_context=turn_context,
            grounding_facts=grounding_facts,
        )
        if outcome is not None:
            return outcome

    planning_route = turn_planning_route.route_with_existing_understanding(
        db=db,
        user=user,
        user_text=user_text,
        understanding=understanding,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
        context_artifacts=context_artifacts,
        coach_bundle=coach_bundle,
        grounding_facts=grounding_facts,
        turn_context=turn_context,
        decision_reply_composer_fn=decision_reply_composer_fn,
        reviewer_request_json_fn=reviewer_request_json_fn,
    )
    if planning_route.outcome is not None:
        if planning_route.apply_turn_plan_memory_commands:
            turn_planning_route.apply_turn_plan_memory_commands_once(
                db=db,
                user=user,
                turn_plan=turn_plan,
                turn_memory_writes=turn_memory_writes,
                turn_context=turn_context,
            )
        return planning_route.outcome

    legacy_skip_reason = coach_decision_runtime.legacy_provider_skip_reason(turn_context)
    coach_decision_runtime.trace_legacy_provider_skipped(turn_context, reason=legacy_skip_reason)
    return coach_decision_runtime.canonical_provider_clarification_outcome(
        reason=legacy_skip_reason,
        user_text=user_text,
        grounding_facts=grounding_facts,
        decision_reply_composer_fn=decision_reply_composer_fn,
    )


def _route_pending_or_command_reply(
    *,
    db: Session,
    user: Any,
    user_text: str,
    understanding: Any,
    turn_plan: Any,
    pending_confirmation: Any,
    grounding_packet: dict[str, object],
    turn_context: dict[str, object],
    understanding_action_result: dict[str, Any] | None,
) -> ConversationTurnOutcome | None:
    pending_outcome = pending_resolution.apply_pending_resolution(
        db=db,
        user=user,
        decision_artifact=None,
        canonical_understanding=understanding,
        pending_confirmation=pending_confirmation,
        user_text=user_text,
        turn_plan=turn_plan,
    )
    if pending_outcome is not None:
        return pending_outcome

    if readonly_reply.should_compose_understanding_command_reply(understanding_action_result):
        return readonly_reply.compose_understanding_command_reply(
            db=db,
            user=user,
            user_text=user_text,
            understanding=understanding,
            turn_context=turn_context,
            grounding=grounding_packet,
            action_result=understanding_action_result or {},
            compose_no_change_reply_for_turn_fn=readonly_reply.compose_no_change_reply_for_turn,
        )
    return None
