from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import mutations, repository as repo
from fitmas.api_payloads import IncomingMessage
from fitmas.conversation_context import (
    activity_claim_summary_for_prompt,
    build_claim_memory_updates,
    build_conversation_context,
    execution_summary_for_prompt,
    signal_summary_for_prompt,
    temporal_summary_for_prompt,
)
from fitmas.db import get_db
from fitmas.llm import MutationDecision, decide, extract_facts, make_plan_summary, make_timeline_summary, select_prompt_facts
from fitmas.models import DayId, Extraction, Message, MessageReply, MessageRole
from fitmas.nlp import extract_reply, generate_reply
from fitmas.signals import collect_signals
from fitmas.tool_contract import ToolContext

logger = logging.getLogger(__name__)

router = APIRouter()

_DAY_VALUES = {d.value for d in DayId}


def _resolve_day_updated(decision: MutationDecision) -> DayId | None:
    """Extract the affected day from a mutation decision."""
    target = decision.to_day or decision.from_day
    if target and target in _DAY_VALUES:
        return DayId(target)
    return None


@router.post("/api/v0/messages", response_model=MessageReply)
def post_message(payload: IncomingMessage, db: Session = Depends(get_db)) -> MessageReply:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    plan = repo.get_active_plan(db, user.id)

    repo.add_message(db, user.id, "user", payload.text)
    logger.info("User message: %s", payload.text[:120])

    msgs = repo.get_messages(db, user.id)
    conversation_history = [{"role": m.role, "text": m.text} for m in msgs]
    pydantic_plan = repo.to_pydantic_plan(plan)
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=21)
    timeline = [repo.to_pydantic_scheduled_session(session) for session in scheduled_sessions]
    activities = repo.get_activities(db, user.id, limit=120)
    today_session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    active_facts = [repo.to_pydantic_fact(fact).model_dump() for fact in repo.get_active_facts(db, user.id)]
    try:
        signals = collect_signals(db, user)
    except Exception:
        logger.exception("Failed to collect conversation signals")
        signals = []
    conversation_context = build_conversation_context(
        user_text=payload.text,
        conversation_history=conversation_history[:-1],
        timezone_name=user.timezone,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        active_facts=active_facts,
        signals=signals,
    )
    claim_facts = build_claim_memory_updates(
        conversation_context,
        activities=activities,
        timezone_name=user.timezone,
        user_text=payload.text,
    )
    if claim_facts:
        repo.upsert_facts(db, user.id, claim_facts)
        active_facts = [repo.to_pydantic_fact(fact).model_dump() for fact in repo.get_active_facts(db, user.id)]
        conversation_context = build_conversation_context(
            user_text=payload.text,
            conversation_history=conversation_history[:-1],
            timezone_name=user.timezone,
            scheduled_sessions=scheduled_sessions,
            activities=activities,
            active_facts=active_facts,
            signals=signals,
        )

    decision = decide(
        payload.text,
        make_plan_summary(pydantic_plan.days),
        timeline_summary=make_timeline_summary(timeline),
        execution_summary=execution_summary_for_prompt(conversation_context),
        temporal_summary=temporal_summary_for_prompt(conversation_context),
        activity_claim_summary=activity_claim_summary_for_prompt(conversation_context),
        signal_summary=signal_summary_for_prompt(conversation_context),
        conversation_history=conversation_history,
        coach_context={
            "coach_name": user.coach_name,
            "coach_style": user.coach_style,
            "coach_relationship": user.coach_relationship,
            "coach_do": user.coach_do,
            "coach_dont": user.coach_dont,
            "coach_soul": user.coach_soul,
            "timezone": user.timezone,
            "today_session_id": today_session.id if today_session else None,
            "selected_facts": list(conversation_context.selected_facts) or select_prompt_facts(active_facts),
        },
        remembered_facts=active_facts,
        time_context=conversation_context.time_context,
        tool_context=ToolContext(
            pipeline="conversation",
            user_id=user.id,
            timezone_name=user.timezone,
            scheduled_sessions=scheduled_sessions,
            activities=activities,
            active_facts=active_facts,
        ),
    )

    day_updated = None
    if decision:
        mutations.apply(db, plan.id, decision)
        reply_text = decision.fitmas_message
        extraction = Extraction(confidence=0.85)
        day_updated = _resolve_day_updated(decision)
        logger.info("LLM reply (%s): %s", decision.mutation_type, reply_text[:120])
    else:
        extraction = extract_reply(payload.text)
        fallback = generate_reply(payload.text, extraction)
        reply_text = fallback.assistant_message.text
        logger.info("Fallback reply: %s", reply_text[:120])

    repo.add_message(db, user.id, "agent", reply_text)
    extracted_facts = extract_facts(payload.text, reply_text, active_facts)
    if extracted_facts:
        repo.upsert_facts(db, user.id, extracted_facts)

        # Adaptive plan: check health facts for automatic adaptation
        try:
            from fitmas.adaptation import check_and_adapt_health_facts
            health_result = check_and_adapt_health_facts(db, user, extracted_facts)
            if health_result and health_result.applied and health_result.message:
                repo.add_message(db, user.id, "agent", health_result.message)
        except Exception:
            logger.exception("Adaptation health_fact check failed (non-blocking)")

    return MessageReply(
        user_message=Message(role=MessageRole.USER, text=payload.text),
        extraction=extraction,
        assistant_message=Message(role=MessageRole.AGENT, text=reply_text),
        day_updated=day_updated,
    )
