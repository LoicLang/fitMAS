from __future__ import annotations

import os
from typing import Any, Callable

from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.decision import DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.legacy.planning_outcome_adapter import planning_decision_to_outcome
from fitmas.legacy.planning_runtime_adapter import run_planning_runtime_attempt_from_legacy_decision
from fitmas.models import Extraction


def planning_runtime_cutover_enabled() -> bool:
    return str(os.getenv("FITMAS_PLANNING_RUNTIME_CUTOVER") or "").strip() not in {"0", "false", "False", "off"}


def maybe_handle_planning_runtime_cutover(
    *,
    decision_artifact,
    canonical_understanding=None,
    understanding_planning_cutover_enabled: bool = False,
    state,
    conversation_context,
    coach_bundle,
    db,
    user,
    source_text: str,
    reviewer_request_json_fn,
    grounding_facts: tuple[str, ...],
    planning_context_from_turn_state_fn: Callable[..., Any],
    decision_reply_composer_fn: Callable[[], Any],
    compose_no_change_reply_for_turn_fn: Callable[..., tuple[str, str | None]],
    turn_context: dict[str, object] | None = None,
    action_result: dict | None = None,
) -> ConversationTurnOutcome | None:
    if not planning_runtime_cutover_enabled():
        return None
    planning_context = planning_context_from_turn_state_fn(
        state=state,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
    )
    planning_understanding = (
        canonical_understanding
        if understanding_planning_cutover_enabled and getattr(canonical_understanding, "intent", None) == "plan_change"
        else None
    )
    attempt = run_planning_runtime_attempt_from_legacy_decision(
        decision_artifact=decision_artifact,
        context=planning_context,
        db=db,
        user=user,
        source_text=source_text,
        coach_state_bundle=coach_bundle,
        reviewer_request_json_fn=reviewer_request_json_fn,
        understanding=planning_understanding,
    )
    if turn_context is not None and canonical_understanding is not None:
        turn_context["planning_runtime_understanding_source"] = (
            "canonical" if planning_understanding is not None else "legacy_adapter"
        )
    if attempt.result is not None:
        return conversation_outcome_from_planning_runtime_result(
            attempt.result,
            db=db,
            user=user,
            user_text=source_text,
            grounding_facts=grounding_facts,
            original_reply=str(getattr(decision_artifact, "reply_hint", "") or ""),
            turn_context=turn_context or {},
            action_result=action_result or {},
            decision_reply_composer_fn=decision_reply_composer_fn,
            compose_no_change_reply_for_turn_fn=compose_no_change_reply_for_turn_fn,
        )
    if attempt.applicable:
        return planning_runtime_unhandled_outcome(
            reason=attempt.reason,
            user_text=source_text,
            grounding_facts=grounding_facts,
            decision_reply_composer_fn=decision_reply_composer_fn,
        )
    return None


def planning_runtime_unhandled_outcome(
    *,
    reason: str,
    user_text: str = "",
    grounding_facts: tuple[str, ...] = (),
    decision_reply_composer_fn: Callable[[], Any],
) -> ConversationTurnOutcome:
    reason_summary = f"Je bloque ce changement pour l'instant: {reason}."
    decision_outcome = DecisionOutcome(
        kind="plan_blocked",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Changement planning bloque",
            reason_summary=reason_summary,
            evidence=("planning_runtime_cutover", reason),
            tradeoff=None,
            impact={},
            protected=("runtime_single_path", "no_legacy_fallthrough"),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="planning_runtime_unhandled",
            audience="conversation",
            allowed_claims=("plan_blocked",),
            forbidden_claims=("plan_committed", "plan_committed_without_event", "execution_updated_without_event"),
        ),
    )
    reply_result = decision_reply_composer_fn().compose(
        decision_outcome,
        context=None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=reply_result.text or reason_summary,
        response_mode="planning_runtime_unhandled",
        mutation_applied=False,
        pending_confirmation=False,
    )


def legacy_decision_contract_disabled_outcome(
    *,
    decision_artifact: Any | None = None,
    user_text: str = "",
    grounding_facts: tuple[str, ...] = (),
    decision_reply_composer_fn: Callable[[], Any],
) -> ConversationTurnOutcome:
    reason_summary = (
        "Je ne peux pas appliquer cette ancienne forme de decision. "
        "Redis-moi le changement voulu et je le reevalue proprement."
    )
    decision_outcome = DecisionOutcome(
        kind="plan_blocked",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Decision non appliquee",
            reason_summary=reason_summary,
            evidence=("legacy_contract_disabled",),
            tradeoff=None,
            impact={},
            protected=("single_planning_runtime", "no_legacy_write"),
            next_step="Redis-moi le changement voulu.",
        ),
        reply_contract=ReplyContract(
            mode="legacy_contract_disabled",
            audience="conversation",
            allowed_claims=("plan_blocked",),
            forbidden_claims=("plan_committed", "plan_committed_without_event", "execution_updated_without_event"),
        ),
    )
    reply_result = decision_reply_composer_fn().compose(
        decision_outcome,
        context=None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=reply_result.text or reason_summary,
        response_mode="legacy_decision_contract_disabled",
        decision=decision_artifact,
        mutation_applied=False,
        pending_confirmation=False,
    )


def conversation_outcome_from_planning_runtime_result(
    result,
    *,
    db=None,
    user=None,
    user_text: str = "",
    grounding_facts: tuple[str, ...] = (),
    original_reply: str = "",
    turn_context: dict[str, object] | None = None,
    action_result: dict | None = None,
    decision_reply_composer_fn: Callable[[], Any],
    compose_no_change_reply_for_turn_fn: Callable[..., tuple[str, str | None]] | None = None,
) -> ConversationTurnOutcome:
    action_result = action_result or {}
    if (
        result.kind == "block"
        and db is not None
        and user is not None
        and int(action_result.get("execution_applied") or 0) > 0
        and compose_no_change_reply_for_turn_fn is not None
    ):
        reply_text, composed_mode = compose_no_change_reply_for_turn_fn(
            db=db,
            user=user,
            user_text=user_text,
            original_reply=original_reply or result.reason,
            turn_context=turn_context or {},
            grounding=None,
            action_result=action_result,
        )
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=reply_text,
            response_mode=composed_mode or "planning_runtime_block_with_execution_update",
            mutation_applied=False,
            pending_confirmation=False,
        )
    decision_outcome = planning_decision_to_outcome(result)
    reply_result = decision_reply_composer_fn().compose(
        decision_outcome,
        context=None,
        user_text=user_text,
        grounding_facts=grounding_facts,
    )
    reply_text = reply_result.text or decision_outcome.explanation.reason_summary
    pending = decision_outcome.kind in {"plan_pending", "plan_choice_pending"}
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=reply_text,
        response_mode=planning_runtime_response_mode_for_outcome_kind(decision_outcome.kind),
        mutation_applied=decision_outcome.kind == "plan_committed",
        pending_confirmation=pending,
        pending_confirmation_id=getattr(result, "pending_confirmation_id", None),
    )


def planning_runtime_response_mode(kind: str) -> str:
    return {
        "commit": "planning_runtime_commit",
        "pending_confirmation": "planning_runtime_pending_confirmation",
        "pending_choice": "planning_runtime_pending_choice",
        "block": "planning_runtime_block",
    }.get(kind, f"planning_runtime_{kind}")


def planning_runtime_response_mode_for_outcome_kind(kind: str) -> str:
    return {
        "plan_committed": "planning_runtime_commit",
        "plan_pending": "planning_runtime_pending_confirmation",
        "plan_choice_pending": "planning_runtime_pending_choice",
        "plan_blocked": "planning_runtime_block",
    }.get(kind, f"planning_runtime_{kind}")
