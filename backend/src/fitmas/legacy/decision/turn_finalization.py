from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from fitmas.legacy.domain.coaching import coach_voice
import fitmas.legacy.llm.gateway as gw
from fitmas.legacy.decision.output_verifier import build_claim_repair_prompt, looks_like_action_claim, outage_fallback_reply
from fitmas.legacy.decision.conversation_contract import (
    ConversationPipelineDependencies,
    ConversationTurnInput,
    ConversationTurnOutcome,
    ConversationTurnState,
)
from fitmas.legacy.decision import pending_resolution
from fitmas.legacy.decision import turn_persistence
from fitmas.legacy.decision.message_models import Extraction, MessageReply


logger = logging.getLogger(__name__)


def record_turn_reply(
    *,
    db: Session,
    user,
    payload: ConversationTurnInput,
    reply_text: str,
    extraction: Extraction,
    response_mode: str,
    turn_context: dict[str, object],
    turn_memory_writes: list[dict],
) -> MessageReply:
    return turn_persistence.reply_and_record_turn(
        db=db,
        user_id=user.id,
        user_text=payload.text,
        reply_text=reply_text,
        extraction=extraction,
        response_mode=response_mode,
        turn_context=turn_context,
        memory_writes=turn_memory_writes,
    )


def record_turn_outcome(
    *,
    db: Session,
    user,
    payload: ConversationTurnInput,
    outcome: ConversationTurnOutcome,
    turn_context: dict[str, object],
    turn_memory_writes: list[dict],
) -> MessageReply:
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


def finalize_and_record_outcome(
    *,
    db: Session,
    user,
    payload: ConversationTurnInput,
    outcome: ConversationTurnOutcome,
    state: ConversationTurnState,
    dependencies: ConversationPipelineDependencies,
    pending_confirmation,
    turn_context: dict[str, object],
    turn_memory_writes: list[dict],
) -> MessageReply:
    mutation_actually_committed = bool(outcome.mutation_applied or outcome.pending_confirmation)
    if not mutation_actually_committed and looks_like_action_claim(outcome.reply_text):
        logger.warning(
            "conversation_turn.finalization.claim_without_mutation user=%s reply=%r",
            user.id,
            outcome.reply_text[:200],
        )
        repaired = _llm_repair_claim_reply(original_reply=outcome.reply_text, user_text=payload.text)
        if repaired:
            outcome.reply_text = repaired
            outcome.response_mode = "claim_without_mutation_repaired"
        else:
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

    return record_turn_outcome(
        db=db,
        user=user,
        payload=payload,
        outcome=outcome,
        turn_context=turn_context,
        turn_memory_writes=turn_memory_writes,
    )


def _llm_repair_claim_reply(*, original_reply: str, user_text: str) -> str | None:
    if not original_reply or not original_reply.strip():
        return None
    system, prompt = build_claim_repair_prompt(original_reply=original_reply, user_text=user_text)
    try:
        repaired = gw.request_text(system=system, prompt=prompt, max_tokens=200)
    except Exception:
        logger.exception("conversation_turn.finalization.claim_repair_llm_error user_text=%r", user_text[:80])
        return None
    if not repaired:
        logger.warning("conversation_turn.finalization.claim_repair_empty user_text=%r", user_text[:80])
        return None
    repaired = repaired.strip()
    if len(repaired) < 5 or len(repaired) > 500:
        logger.warning("conversation_turn.finalization.claim_repair_bad_length len=%d", len(repaired))
        return None
    if looks_like_action_claim(repaired):
        logger.warning("conversation_turn.finalization.claim_repair_still_claims reply=%r", repaired[:160])
        return None
    if coach_voice.message_violates_coach_voice(repaired):
        logger.warning("conversation_turn.finalization.claim_repair_voice_violation reply=%r", repaired[:160])
        return None
    if coach_voice.message_looks_receipt_style(repaired):
        logger.warning("conversation_turn.finalization.claim_repair_receipt_style reply=%r", repaired[:160])
    return repaired
