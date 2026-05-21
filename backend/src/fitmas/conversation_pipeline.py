from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.calibration_llm import extract_calibration_resolution
from fitmas import coach_voice
import fitmas.llm.gateway as gw
from fitmas.claim_guard import (
    build_claim_repair_prompt,
    looks_like_action_claim,
    outage_fallback_reply,
)
from fitmas.decision import DecisionReplyComposer
from fitmas.calibration_needs import (
    build_resolution_memory_updates,
    find_open_calibration_need,
    should_apply_calibration_resolution,
)
from fitmas.llm.reply_decision_backend import LLMReplyBackend
from fitmas.decision import clarification_reply
from fitmas.decision import command_application
from fitmas.decision import pending_resolution
from fitmas.decision import planning_runtime
from fitmas.decision import activity_highlight
from fitmas.decision import readonly_reply
from fitmas.decision import coach_decision_runtime
from fitmas.decision import turn_context as turn_context_builder
from fitmas.decision import turn_idempotency
from fitmas.decision import turn_persistence
from fitmas.decision import turn_state
import fitmas.llm.reply_backend as final_reply
from fitmas.decision import understanding_runtime
from fitmas.conversation_contract import (
    ConversationPipelineDependencies,
    ConversationTurnInput,
    ConversationTurnOutcome,
    ConversationUserNotFoundError,
)
from fitmas.models import Extraction, MessageReply

logger = logging.getLogger(__name__)


def run_conversation_turn(
    payload: ConversationTurnInput,
    *,
    db: Session,
    dependencies: ConversationPipelineDependencies,
) -> MessageReply:
    user = repo.get_user_optional(db)
    if user is None:
        raise ConversationUserNotFoundError("No onboarded user yet")

    with turn_idempotency.client_message_key_lock(user.id, payload.client_message_key):
        return _run_conversation_turn_impl(payload, db=db, dependencies=dependencies)


def _run_conversation_turn_impl(
    payload: ConversationTurnInput,
    *,
    db: Session,
    dependencies: ConversationPipelineDependencies,
) -> MessageReply:
    user = repo.get_user_optional(db)
    if user is None:
        raise ConversationUserNotFoundError("No onboarded user yet")

    duplicate_reply = turn_idempotency.reply_for_duplicate_client_message(db=db, user_id=user.id, payload=payload)
    if duplicate_reply is not None:
        return duplicate_reply

    state = turn_state.load_turn_state(db=db, user=user, user_text=payload.text)
    turn_memory_writes: list[dict] = []
    pending_confirmation = repo.get_active_pending_mutation_confirmation(db, user.id)

    open_calibration_need = find_open_calibration_need(state.active_memory_rows)
    calibration_resolution = None
    if open_calibration_need is not None:
        calibration_resolution = extract_calibration_resolution(
            user_text=payload.text,
            need=open_calibration_need,
            timezone_name=user.timezone,
            coach_context={
                "coach_name": user.coach_name,
                "coach_style": user.coach_style,
                "coach_relationship": user.coach_relationship,
                "coach_do": user.coach_do,
                "coach_dont": user.coach_dont,
                "coach_soul": user.coach_soul,
            },
        )
        if should_apply_calibration_resolution(calibration_resolution):
            turn_persistence.persist_turn_memory_updates(
                db,
                user.id,
                build_resolution_memory_updates(open_calibration_need, calibration_resolution),
                turn_memory_writes=turn_memory_writes,
            )
            state.active_memory_rows, state.active_facts = turn_state.active_memory_payloads(db, user.id)

    context_artifacts = turn_context_builder.build_turn_context_artifacts(
        db=db,
        user=user,
        payload=payload,
        state=state,
        dependencies=dependencies,
        pending_confirmation=pending_confirmation,
    )
    conversation_context = context_artifacts.conversation_context
    coach_bundle = context_artifacts.coach_bundle
    turn_plan = context_artifacts.turn_plan
    unresolved_execution_followup_text = context_artifacts.unresolved_execution_followup_text
    grounding_packet = context_artifacts.grounding_packet
    grounding_facts = context_artifacts.grounding_facts
    turn_context = context_artifacts.turn_context

    if _should_use_terminal_close_path(
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
        return turn_persistence.reply_and_record_turn(
            db=db,
            user_id=user.id,
            user_text=payload.text,
            reply_text=reply_text,
            extraction=Extraction(confidence=float(getattr(turn_plan, "confidence", 0.95) or 0.95)),
            response_mode="close_turn_composed",
            turn_context=turn_context,
            memory_writes=turn_memory_writes,
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
            return turn_persistence.reply_and_record_turn(
                db=db,
                user_id=user.id,
                user_text=payload.text,
                reply_text=pending_outcome.reply_text,
                extraction=pending_outcome.extraction,
                response_mode=pending_outcome.response_mode,
                mutation_applied=pending_outcome.mutation_applied,
                pending_confirmation=pending_outcome.pending_confirmation,
                pending_confirmation_id=pending_outcome.pending_confirmation_id,
                turn_context=turn_context,
                memory_writes=turn_memory_writes,
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
        return turn_persistence.reply_and_record_turn(
            db=db,
            user_id=user.id,
            user_text=payload.text,
            reply_text=canonical_clarification_outcome.reply_text,
            extraction=canonical_clarification_outcome.extraction,
            response_mode=canonical_clarification_outcome.response_mode,
            mutation_applied=canonical_clarification_outcome.mutation_applied,
            pending_confirmation=canonical_clarification_outcome.pending_confirmation,
            turn_context=turn_context,
            memory_writes=turn_memory_writes,
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
                return turn_persistence.reply_and_record_turn(
                    db=db,
                    user_id=user.id,
                    user_text=payload.text,
                    reply_text=canonical_planning_outcome.reply_text,
                    extraction=canonical_planning_outcome.extraction,
                    response_mode=canonical_planning_outcome.response_mode,
                    mutation_applied=canonical_planning_outcome.mutation_applied,
                    pending_confirmation=canonical_planning_outcome.pending_confirmation,
                    pending_confirmation_id=canonical_planning_outcome.pending_confirmation_id,
                    turn_context=turn_context,
                    memory_writes=turn_memory_writes,
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
                    return turn_persistence.reply_and_record_turn(
                        db=db,
                        user_id=user.id,
                        user_text=payload.text,
                        reply_text=canonical_planning_outcome.reply_text,
                        extraction=canonical_planning_outcome.extraction,
                        response_mode=canonical_planning_outcome.response_mode,
                        mutation_applied=canonical_planning_outcome.mutation_applied,
                        pending_confirmation=canonical_planning_outcome.pending_confirmation,
                        pending_confirmation_id=canonical_planning_outcome.pending_confirmation_id,
                        turn_context=turn_context,
                        memory_writes=turn_memory_writes,
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
        return turn_persistence.reply_and_record_turn(
            db=db,
            user_id=user.id,
            user_text=payload.text,
            reply_text=activity_highlight_outcome.reply_text,
            extraction=activity_highlight_outcome.extraction,
            response_mode=activity_highlight_outcome.response_mode,
            mutation_applied=activity_highlight_outcome.mutation_applied,
            pending_confirmation=activity_highlight_outcome.pending_confirmation,
            turn_context=turn_context,
            memory_writes=turn_memory_writes,
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
        # Chantier 1 (autonomy refactor): the only remaining path here is
        # "decide() returned None and there is no deterministic adaptation
        # to fall back on" — typically the Anthropic client is unavailable.
        # Reply soberly: do not assert any plan state, do not regurgitate
        # rule-based phrases that could lie about the situation.
        logger.warning("conversation_pipeline: decide() returned None with no fallback decision")
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

    mutation_actually_committed = bool(outcome.mutation_applied or outcome.pending_confirmation)
    if not mutation_actually_committed and looks_like_action_claim(outcome.reply_text):
        original_reply = outcome.reply_text
        logger.warning(
            "conversation_pipeline.claim_without_mutation user=%s reply=%r",
            user.id,
            original_reply[:200],
        )
        # Doctrine-correct path (Chantier 1bis - 3 mai 2026) : LLM repair plutot
        # qu'une template canned. La canned "Je n'ai applique aucun changement..."
        # produisait du receipt-style en aval de Chantier 1 voix unifiee.
        repaired = _llm_repair_claim_reply(original_reply=original_reply, user_text=payload.text)
        if repaired:
            outcome.reply_text = repaired
            outcome.response_mode = "claim_without_mutation_repaired"
        else:
            # Outage minimal (LLM down ou repair invalide) : ligne coach-voice
            # courte, jamais la vieille template administrative.
            outcome.reply_text = outage_fallback_reply()
            outcome.response_mode = "claim_without_mutation_outage_fallback"

    extracted_facts = (
        []
        if outcome.response_mode == "obsolete_turn_no_write"
        else dependencies.extract_facts(payload.text, outcome.reply_text, state.active_facts)
    )
    extracted_facts = turn_persistence.filter_legacy_extracted_facts(extracted_facts)
    if extracted_facts:
        turn_persistence.persist_turn_memory_updates(
            db,
            user.id,
            extracted_facts,
            turn_memory_writes=turn_memory_writes,
        )

    pending_resolution.supersede_pending_if_replaced(
        db=db,
        outcome=outcome,
        pending_confirmation=pending_confirmation,
    )

    return turn_persistence.reply_and_record_turn(
        db=db,
        user_id=user.id,
        user_text=payload.text,
        reply_text=outcome.reply_text,
        extraction=outcome.extraction,
        day_updated=outcome.day_updated,
        response_mode=outcome.response_mode,
        decision=outcome.decision,
        mutation_applied=outcome.mutation_applied,
        pending_confirmation=outcome.pending_confirmation,
        pending_confirmation_id=outcome.pending_confirmation_id,
        turn_context=turn_context,
        memory_writes=turn_memory_writes,
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


def _llm_repair_claim_reply(*, original_reply: str, user_text: str) -> str | None:
    """LLM repair pour un reply qui claim une action sans mutation committee.

    Retourne le texte reecrit (voix coach, sans claim) si valide, sinon None.
    Critères de validation:
      - non vide / non whitespace
      - ne claim plus une action (`looks_like_action_claim`)
      - ne viole pas la voix coach (`coach_voice.message_violates_coach_voice`)
      - longueur raisonnable (< 500 chars, anti runaway)

    En cas d'echec (LLM down, output invalide), le caller doit retomber sur
    `outage_fallback_reply()` (voir `claim_guard`).
    """
    if not original_reply or not original_reply.strip():
        return None
    system, prompt = build_claim_repair_prompt(original_reply=original_reply, user_text=user_text)
    try:
        repaired = gw.request_text(system=system, prompt=prompt, max_tokens=200)
    except Exception:
        logger.exception("conversation_pipeline.claim_repair_llm_error user_text=%r", user_text[:80])
        return None
    if not repaired:
        logger.warning("conversation_pipeline.claim_repair_empty user_text=%r", user_text[:80])
        return None
    repaired = repaired.strip()
    if len(repaired) < 5 or len(repaired) > 500:
        logger.warning("conversation_pipeline.claim_repair_bad_length len=%d", len(repaired))
        return None
    if looks_like_action_claim(repaired):
        logger.warning("conversation_pipeline.claim_repair_still_claims reply=%r", repaired[:160])
        return None
    if coach_voice.message_violates_coach_voice(repaired):
        logger.warning("conversation_pipeline.claim_repair_voice_violation reply=%r", repaired[:160])
        return None
    if coach_voice.message_looks_receipt_style(repaired):
        # Log only — pas un blocker, mais signale la regression.
        logger.warning("conversation_pipeline.claim_repair_receipt_style reply=%r", repaired[:160])
    return repaired


def _should_use_terminal_close_path(
    *,
    turn_plan,
    pending_confirmation,
    open_calibration_need,
) -> bool:
    if turn_plan is None:
        return False
    if str(getattr(turn_plan, "primary_intent", "") or "") not in {"close_turn", "trivial_ack"}:
        return False
    if bool(getattr(turn_plan, "has_plan_mutation", False)):
        return False
    if tuple(getattr(turn_plan, "secondary_intents", ()) or ()):
        return False
    if pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending":
        return False
    if open_calibration_need is not None:
        return False
    return True
