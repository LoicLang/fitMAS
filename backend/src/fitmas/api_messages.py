from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import mutations, repository as repo
from fitmas.activity_claims import (
    build_claim_correction_payloads,
    build_claim_fact_payloads,
    extract_activity_claim,
    extract_recent_activity_claim,
    format_activity_claim_for_prompt,
    is_activity_claim_correction,
)
from fitmas.api_payloads import IncomingMessage
from fitmas.db import get_db
from fitmas.execution_context import build_today_execution_context, format_execution_context_for_prompt
from fitmas.llm import decide, extract_facts, make_plan_summary, make_timeline_summary, select_prompt_facts
from fitmas.models import Extraction, Message, MessageReply, MessageRole
from fitmas.nlp import extract_reply, generate_reply
from fitmas.temporal_resolver import format_temporal_resolution_for_prompt, resolve_temporal_context
from fitmas.time_context import build_time_context

logger = logging.getLogger(__name__)

router = APIRouter()


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
    time_context = build_time_context(user.timezone)
    temporal_resolution = resolve_temporal_context(
        payload.text,
        timezone_name=user.timezone,
    )
    previous_activity_claim = extract_recent_activity_claim(
        conversation_history[:-1],
        current_text="",
        timezone_name=user.timezone,
    )
    current_activity_claim = extract_activity_claim(
        payload.text,
        timezone_name=user.timezone,
    )
    recent_activity_claim = extract_recent_activity_claim(
        conversation_history[:-1],
        current_text=payload.text,
        timezone_name=user.timezone,
    )
    if current_activity_claim is not None:
        claim_facts = build_claim_fact_payloads(
            recent_activity_claim,
            activities=activities,
            timezone_name=user.timezone,
        )
        if is_activity_claim_correction(payload.text, timezone_name=user.timezone):
            claim_facts.extend(
                build_claim_correction_payloads(
                    previous_activity_claim,
                    recent_activity_claim,
                )
            )
        if claim_facts:
            repo.upsert_facts(db, user.id, claim_facts)

    active_facts = [repo.to_pydantic_fact(fact).model_dump() for fact in repo.get_active_facts(db, user.id)]
    execution_context = build_today_execution_context(
        timezone_name=user.timezone,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
    )

    decision = decide(
        payload.text,
        make_plan_summary(pydantic_plan.days),
        timeline_summary=make_timeline_summary(timeline),
        execution_summary=format_execution_context_for_prompt(execution_context),
        temporal_summary=format_temporal_resolution_for_prompt(temporal_resolution),
        activity_claim_summary=format_activity_claim_for_prompt(recent_activity_claim),
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
            "selected_facts": select_prompt_facts(active_facts),
        },
        remembered_facts=active_facts,
        time_context=time_context,
    )

    if decision:
        mutations.apply(db, plan.id, decision)
        reply_text = decision.fitmas_message
        extraction = Extraction(confidence=0.85)
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

    return MessageReply(
        user_message=Message(role=MessageRole.USER, text=payload.text),
        extraction=extraction,
        assistant_message=Message(role=MessageRole.AGENT, text=reply_text),
    )
