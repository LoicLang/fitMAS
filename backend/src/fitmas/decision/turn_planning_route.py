from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from fitmas.decision.conversation_contract import ConversationTurnOutcome, ConversationTurnState
from fitmas.decision import planning_runtime
from fitmas.decision import turn_context as turn_context_builder


@dataclass(frozen=True, slots=True)
class PlanningRouteResult:
    outcome: ConversationTurnOutcome | None = None
    canonical_understanding: Any | None = None
    apply_turn_plan_memory_commands: bool = False
    understanding_refreshed: bool = False


def route_pre_understanding_planning(
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
    grounding_facts: tuple[str, ...],
    turn_context: dict[str, object],
    decision_reply_composer_fn: Callable[[], Any],
    reviewer_request_json_fn: Callable[..., Any],
) -> PlanningRouteResult:
    if not planning_runtime.should_prepare_canonical_planning_understanding(
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
    ):
        return PlanningRouteResult()

    planning_runtime.trace_canonical_planning_prepared(
        turn_context,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
    )
    canonical_understanding = _run_planning_understanding(
        user=user,
        user_text=user_text,
        turn_plan=turn_plan,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
        state=state,
        pending_confirmation=pending_confirmation,
        turn_context=turn_context,
    )
    outcome, apply_memory = _handle_planning_if_applicable(
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
        decision_reply_composer_fn=decision_reply_composer_fn,
        reviewer_request_json_fn=reviewer_request_json_fn,
        handle_unsupported=True,
        trace_not_used=True,
    )
    return PlanningRouteResult(
        outcome=outcome,
        canonical_understanding=canonical_understanding,
        apply_turn_plan_memory_commands=apply_memory,
        understanding_refreshed=True,
    )


def route_with_existing_understanding(
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
    decision_reply_composer_fn: Callable[[], Any],
    reviewer_request_json_fn: Callable[..., Any],
) -> PlanningRouteResult:
    outcome, apply_memory = _handle_planning_if_applicable(
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
        handle_unsupported=True,
        trace_not_used=False,
    )
    return PlanningRouteResult(
        outcome=outcome,
        canonical_understanding=understanding,
        apply_turn_plan_memory_commands=apply_memory,
    )


def apply_turn_plan_memory_commands_once(
    *,
    db: Session,
    user: Any,
    turn_plan: Any,
    turn_memory_writes: list[dict],
    turn_context: dict[str, object],
) -> None:
    if "turn_plan_memory_action_result" in turn_context:
        return

    from fitmas.decision import command_application

    command_application.apply_turn_plan_memory_commands(
        db=db,
        user=user,
        turn_plan=turn_plan,
        turn_memory_writes=turn_memory_writes,
        turn_context=turn_context,
    )


def _run_planning_understanding(
    *,
    user: Any,
    user_text: str,
    turn_plan: Any,
    conversation_context: Any,
    coach_bundle: Any,
    state: ConversationTurnState,
    pending_confirmation: Any,
    turn_context: dict[str, object],
) -> Any:
    from fitmas.decision import understanding_runtime

    return understanding_runtime.run_canonical_understanding_shadow(
        user=user,
        user_text=user_text,
        turn_plan=turn_plan,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
        state=state,
        pending_confirmation=pending_confirmation,
        turn_context=turn_context,
    )


def _handle_planning_if_applicable(
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
    decision_reply_composer_fn: Callable[[], Any],
    reviewer_request_json_fn: Callable[..., Any],
    handle_unsupported: bool,
    trace_not_used: bool,
) -> tuple[ConversationTurnOutcome | None, bool]:
    planning_understanding = planning_runtime.planning_understanding_for_provider(
        understanding=understanding,
        turn_plan=turn_plan,
    )
    if planning_understanding is not understanding:
        turn_context.setdefault("canonical_planning_provider", {})["understanding_source"] = "turn_plan"

    if planning_runtime.should_use_canonical_planning_without_legacy(
        understanding=planning_understanding,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
    ):
        outcome = _handle_planning(
            db=db,
            user=user,
            user_text=user_text,
            understanding=planning_understanding,
            context_artifacts=context_artifacts,
            coach_bundle=coach_bundle,
            grounding_facts=grounding_facts,
            turn_context=turn_context,
            decision_reply_composer_fn=decision_reply_composer_fn,
            reviewer_request_json_fn=reviewer_request_json_fn,
        )
        return outcome, outcome is not None

    if handle_unsupported and planning_runtime.should_handle_unsupported_canonical_planning_without_legacy(
        understanding=planning_understanding,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
    ):
        outcome = _handle_planning(
            db=db,
            user=user,
            user_text=user_text,
            understanding=planning_understanding,
            context_artifacts=context_artifacts,
            coach_bundle=coach_bundle,
            grounding_facts=grounding_facts,
            turn_context=turn_context,
            decision_reply_composer_fn=decision_reply_composer_fn,
            reviewer_request_json_fn=reviewer_request_json_fn,
        )
        return outcome, False

    if trace_not_used:
        planning_runtime.trace_canonical_planning_not_used(
            turn_context,
            understanding=planning_understanding,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
        )
    return None, False


def _handle_planning(
    *,
    db: Session,
    user: Any,
    user_text: str,
    understanding: Any,
    context_artifacts: turn_context_builder.TurnContextArtifacts,
    coach_bundle: Any,
    grounding_facts: tuple[str, ...],
    turn_context: dict[str, object],
    decision_reply_composer_fn: Callable[[], Any],
    reviewer_request_json_fn: Callable[..., Any],
) -> ConversationTurnOutcome | None:
    return planning_runtime.handle_canonical_planning(
        understanding=understanding,
        context=turn_context_builder.planning_context_from_artifacts(context_artifacts),
        db=db,
        user=user,
        source_text=user_text,
        coach_state_bundle=coach_bundle,
        reviewer_request_json_fn=reviewer_request_json_fn,
        grounding_facts=grounding_facts,
        decision_reply_composer_fn=decision_reply_composer_fn,
        turn_context=turn_context,
    )
