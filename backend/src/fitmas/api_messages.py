from __future__ import annotations

import logging
import unicodedata
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import mutations, repository as repo
from fitmas.adaptation import check_and_adapt_health_facts
from fitmas.adaptation_log import build_adaptation_log_entry
from fitmas.execution_evidence import classify_execution_evidence
from fitmas.athlete_profile import build_athlete_profile
from fitmas.api_payloads import IncomingMessage
from fitmas.calibration_llm import extract_calibration_resolution, generate_calibration_ack
from fitmas.calibration_needs import (
    build_resolution_memory_updates,
    find_open_calibration_need,
    is_standalone_calibration_answer,
    should_apply_calibration_resolution,
)
from fitmas.conversation_context import (
    activity_claim_summary_for_prompt,
    build_claim_memory_updates,
    build_conversation_context,
    execution_summary_for_prompt,
    non_completion_summary_for_prompt,
    signal_summary_for_prompt,
    temporal_summary_for_prompt,
)
from fitmas.db import get_db
from fitmas.llm import MutationDecision, decide, extract_facts, make_plan_summary, make_timeline_summary, select_prompt_facts
from fitmas.memory_profile import upsert_profile_memory
from fitmas.memory_routing import split_memory_payloads
from fitmas.models import DayId, Extraction, Message, MessageReply, MessageRole
from fitmas.nlp import extract_reply, generate_reply
from fitmas.planning_window_resolution import resolve_planning_window
from fitmas.replan_from_life_change import (
    maybe_replan_from_life_change,
    maybe_replan_from_user_indication,
)
from fitmas.signals import collect_signals
from fitmas.tool_contract import ToolContext
from fitmas.user_indication_llm import interpret_user_indication
from fitmas.user_indications import (
    UserIndication,
    UserIndicationKind,
    UserIndicationPolarity,
    UserIndicationScope,
    build_health_fact_payloads_from_indication,
    supports_planning_resolution,
)
from fitmas.time_context import get_timezone

logger = logging.getLogger(__name__)

router = APIRouter()

_DAY_VALUES = {d.value for d in DayId}
_ACK_TEXTS = {"ok", "ok merci", "merci", "ca marche", "c est bon", "c'est bon", "top merci", "bien recu"}
_GREETING_TEXTS = {"salut", "bonjour", "hello", "yo"}
_MOTIVATION_TEXTS = {
    "je suis motive",
    "je suis motive cette semaine",
    "je suis motive en ce moment",
    "je suis chaud",
    "je suis chaud cette semaine",
}


def _resolve_day_updated(decision: MutationDecision) -> DayId | None:
    """Extract the affected day from a mutation decision."""
    target = decision.to_day or decision.from_day
    if target and target in _DAY_VALUES:
        return DayId(target)
    return None


def _to_mutation_decision(proposed, *, fitmas_message: str) -> MutationDecision:
    return MutationDecision(
        mutation_type=proposed.mutation_type,
        target_session_id=proposed.target_session_id,
        second_session_id=None,
        target_date=proposed.target_date,
        from_day=proposed.from_day,
        to_day=proposed.to_day,
        new_title=proposed.new_title,
        new_goal=proposed.new_goal,
        new_sport_type=proposed.new_sport_type,
        new_session_type=proposed.new_session_type,
        new_duration_min=proposed.new_duration_min,
        new_intensity=proposed.new_intensity,
        new_description=proposed.new_description,
        rationale=proposed.rationale,
        fitmas_message=fitmas_message,
    )


def _normalize_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.lower().strip().split())


def _maybe_low_signal_reply(text: str, *, has_open_calibration_need: bool) -> str | None:
    if has_open_calibration_need:
        return None
    normalized = _normalize_text(text)
    if normalized in _ACK_TEXTS:
        return "Bien recu."
    if normalized in _GREETING_TEXTS:
        return "Salut."
    if normalized in _MOTIVATION_TEXTS:
        return "Bien. On garde cette energie, rien a changer pour l'instant."
    return None


def _week_scope_reply(indication: UserIndication | None, resolution) -> str | None:
    if indication is None or indication.kind is not UserIndicationKind.AVAILABILITY_CONSTRAINT:
        return None
    if indication.scope is not UserIndicationScope.WEEK or resolution is None:
        return None
    if resolution.matched_session_id is not None:
        return None

    if not resolution.candidate_sessions:
        return f"OK. Je n'ai rien de sensible planifie sur {resolution.reference_label}. Rien a proteger la-dessus."

    parts = []
    for candidate in resolution.candidate_sessions[:3]:
        parts.append(f"{candidate.session_title} le {candidate.scheduled_date.isoformat()}")
    sessions_brief = ", ".join(parts)
    if indication.polarity is UserIndicationPolarity.UNAVAILABLE:
        return (
            f"OK. Dans cette fenetre j'ai {sessions_brief}. "
            "Si tu es off complet pendant ce bloc, je les retire et je garde le reste propre. "
            "Tu confirmes qu'on part sur off complet ?"
        )
    return (
        f"OK. Dans cette fenetre j'ai {sessions_brief}. "
        "Tu gardes un petit creneau en deplacement, ou je pars sur une version tres legere ?"
    )


def _human_time_label(indication: UserIndication | None, resolution) -> str:
    label = ""
    if indication is not None and indication.time_reference is not None:
        label = indication.time_reference.label or ""
    elif resolution is not None:
        label = resolution.reference_label or ""
    if label.startswith("explicit_"):
        label = label.removeprefix("explicit_")
    normalized = (
        label.replace("morning", "matin")
        .replace("midday", "midi")
        .replace("evening", "soir")
        .replace("monday", "lundi")
        .replace("tuesday", "mardi")
        .replace("wednesday", "mercredi")
        .replace("thursday", "jeudi")
        .replace("friday", "vendredi")
        .replace("saturday", "samedi")
        .replace("sunday", "dimanche")
        .strip()
    )
    return normalized or "sur ce creneau"


def _no_candidate_constraint_reply(indication: UserIndication | None, resolution) -> str | None:
    if indication is None or indication.kind is not UserIndicationKind.AVAILABILITY_CONSTRAINT:
        return None
    if resolution is None or resolution.candidate_sessions:
        return None
    if indication.scope not in {UserIndicationScope.SINGLE_WINDOW, UserIndicationScope.SINGLE_DAY}:
        return None
    return f"OK. Je n'ai rien de sensible planifie {_human_time_label(indication, resolution)}. Rien a bouger pour l'instant."


def _active_memory_payloads(db: Session, user_id: int) -> tuple[list[object], list[dict]]:
    rows = repo.get_active_memory_items(
        db,
        user_id,
        profile_limit=24,
        working_limit=24,
        include_patterns=True,
        pattern_limit=6,
        total_limit=36,
    )
    return rows, [repo.to_pydantic_fact(row).model_dump() for row in rows]


def _persist_memory_updates(db: Session, user_id: int, payloads: list[dict]) -> None:
    profile_payloads, working_payloads = split_memory_payloads(payloads)
    if profile_payloads:
        upsert_profile_memory(db, user_id, profile_payloads)
    if working_payloads:
        repo.upsert_working_memory(db, user_id, working_payloads)


def _value(obj, key: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _coerce_local_date(value, *, timezone_name: str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(get_timezone(timezone_name)).date()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.date()
        return parsed.astimezone(get_timezone(timezone_name)).date()
    return None


def _execution_contestation_reply(
    *,
    db: Session,
    user,
    scheduled_sessions,
    activities,
    timezone_name: str | None,
    non_completion_claim,
) -> str | None:
    if non_completion_claim is None or non_completion_claim.resolved_date_iso is None:
        return None

    target_date = date.fromisoformat(non_completion_claim.resolved_date_iso)
    sessions_on_date = [
        session
        for session in scheduled_sessions
        if _coerce_local_date(_value(session, "scheduled_date"), timezone_name=timezone_name) == target_date
        and str(_value(session, "sport_type") or "").lower() != "rest"
    ]
    target_session = next(
        (
            session
            for session in sessions_on_date
            if non_completion_claim.sport_type
            and str(_value(session, "sport_type") or "").lower() == non_completion_claim.sport_type
        ),
        sessions_on_date[0] if len(sessions_on_date) == 1 else None,
    )
    activities_on_date = [
        activity
        for activity in activities
        if _coerce_local_date(_value(activity, "started_at") or _value(activity, "created_at"), timezone_name=timezone_name) == target_date
    ]
    evidence = classify_execution_evidence(
        planned_session=target_session,
        activities=activities_on_date,
    )
    if evidence.display_status == "confirmed_done":
        return None

    if target_session is not None and str(_value(target_session, "completion_status") or "").lower() == "done":
        updated_session = repo.set_scheduled_session_status(db, int(_value(target_session, "id")), "skipped")
        if updated_session is not None:
            _, day_plan = repo.get_current_week_day_plan_for_session(db, user=user, session=updated_session)
            if day_plan is not None and str(day_plan.completion_status or "").lower() == "done":
                day_plan.completion_status = "skipped"
                db.commit()

    title = str(_value(target_session, "session_title") or "").strip()
    if title:
        subject = title.lower()
    elif non_completion_claim.sport_type:
        sport_labels = {
            "running": "cette sortie running",
            "swimming": "cette seance natation",
            "cycling": "cette sortie velo",
            "strength": "cette seance renfo",
            "climbing": "cette seance escalade",
        }
        subject = sport_labels.get(non_completion_claim.sport_type, "cette seance")
    else:
        subject = "cette seance"
    return f"OK. Je ne compte pas {subject} comme faite. Je repars de ce que tu me dis, pas d'une validation implicite."


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
    active_memory_rows, active_facts = _active_memory_payloads(db, user.id)
    open_calibration_need = find_open_calibration_need(active_memory_rows)
    low_signal_reply = _maybe_low_signal_reply(payload.text, has_open_calibration_need=open_calibration_need is not None)
    if low_signal_reply is not None:
        repo.add_message(db, user.id, "agent", low_signal_reply)
        return MessageReply(
            user_message=Message(role=MessageRole.USER, text=payload.text),
            extraction=Extraction(confidence=0.95),
            assistant_message=Message(role=MessageRole.AGENT, text=low_signal_reply),
            day_updated=None,
        )
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
            _persist_memory_updates(
                db,
                user.id,
                build_resolution_memory_updates(open_calibration_need, calibration_resolution),
            )
            active_memory_rows, active_facts = _active_memory_payloads(db, user.id)
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
    claim_summary = activity_claim_summary_for_prompt(conversation_context)
    non_completion_summary = non_completion_summary_for_prompt(conversation_context)
    if non_completion_summary:
        claim_summary = "\n".join(part for part in (claim_summary, non_completion_summary) if part)
    claim_facts = build_claim_memory_updates(
        conversation_context,
        activities=activities,
        timezone_name=user.timezone,
        user_text=payload.text,
    )
    if claim_facts:
        _persist_memory_updates(db, user.id, claim_facts)
        active_memory_rows, active_facts = _active_memory_payloads(db, user.id)
        conversation_context = build_conversation_context(
            user_text=payload.text,
            conversation_history=conversation_history[:-1],
            timezone_name=user.timezone,
            scheduled_sessions=scheduled_sessions,
            activities=activities,
            active_facts=active_facts,
            signals=signals,
        )
        claim_summary = activity_claim_summary_for_prompt(conversation_context)
        non_completion_summary = non_completion_summary_for_prompt(conversation_context)
        if non_completion_summary:
            claim_summary = "\n".join(part for part in (claim_summary, non_completion_summary) if part)

    profile_snapshot = build_athlete_profile(user, facts=active_memory_rows)
    user_indication = interpret_user_indication(
        payload.text,
        timezone_name=user.timezone,
    )
    health_indication_facts = build_health_fact_payloads_from_indication(user_indication)
    health_indication_handled = bool(health_indication_facts)
    if health_indication_facts:
        _persist_memory_updates(db, user.id, health_indication_facts)
        active_memory_rows, active_facts = _active_memory_payloads(db, user.id)

        health_result = check_and_adapt_health_facts(db, user, health_indication_facts)
        if health_result and health_result.applied and health_result.message:
            first_decision = health_result.decisions[0] if health_result.decisions else None
            extraction = Extraction(confidence=max(float(user_indication.confidence if user_indication else 0.0), 0.85))
            reply_text = health_result.message
            repo.add_message(db, user.id, "agent", reply_text)
            return MessageReply(
                user_message=Message(role=MessageRole.USER, text=payload.text),
                extraction=extraction,
                assistant_message=Message(role=MessageRole.AGENT, text=reply_text),
                day_updated=_resolve_day_updated(first_decision) if first_decision is not None else None,
            )

    adaptation = maybe_replan_from_life_change(
        user_text=payload.text,
        today=conversation_context.temporal_resolution.local_date,
        time_context=conversation_context.time_context,
        profile=profile_snapshot,
        week_plan=pydantic_plan,
        planning_decision=repo.get_latest_planning_decision_record(db, user.id),
        today_session=today_session,
        scheduled_sessions=scheduled_sessions,
    )
    if adaptation is None and user_indication is not None and supports_planning_resolution(user_indication):
        resolution = resolve_planning_window(
            indication=user_indication,
            scheduled_sessions=scheduled_sessions,
            timezone_name=user.timezone,
        )
        adaptation = maybe_replan_from_user_indication(
            indication=user_indication,
            resolution=resolution,
            today=conversation_context.temporal_resolution.local_date,
            profile=profile_snapshot,
            week_plan=pydantic_plan,
            planning_decision=repo.get_latest_planning_decision_record(db, user.id),
            today_session=today_session,
            scheduled_sessions=scheduled_sessions,
        )
    else:
        resolution = None

    week_scope_reply = None
    no_candidate_reply = None
    if adaptation is None and user_indication is not None and user_indication.kind is UserIndicationKind.AVAILABILITY_CONSTRAINT:
        if resolution is None and user_indication.time_reference is not None:
            resolution = resolve_planning_window(
                indication=user_indication,
                scheduled_sessions=scheduled_sessions,
                timezone_name=user.timezone,
            )
        no_candidate_reply = _no_candidate_constraint_reply(user_indication, resolution)
        week_scope_reply = _week_scope_reply(user_indication, resolution)

    calibration_only_reply = None
    execution_contestation_reply = _execution_contestation_reply(
        db=db,
        user=user,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        timezone_name=user.timezone,
        non_completion_claim=conversation_context.non_completion_claim,
    )
    if (
        open_calibration_need is not None
        and should_apply_calibration_resolution(calibration_resolution)
        and adaptation is None
        and is_standalone_calibration_answer(payload.text)
    ):
        calibration_only_reply = generate_calibration_ack(
            need=open_calibration_need,
            resolution=calibration_resolution,
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

    decision = decide(
        payload.text,
        make_plan_summary(pydantic_plan.days),
        timeline_summary=make_timeline_summary(timeline),
        execution_summary=execution_summary_for_prompt(conversation_context),
        temporal_summary=temporal_summary_for_prompt(conversation_context),
        activity_claim_summary=claim_summary,
        signal_summary=signal_summary_for_prompt(conversation_context),
        conversation_history=conversation_history[:-1],
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
    ) if adaptation is None and calibration_only_reply is None and week_scope_reply is None and no_candidate_reply is None and execution_contestation_reply is None else (
        _to_mutation_decision(adaptation.selected_scenario.mutation, fitmas_message=adaptation.user_message)
        if adaptation is not None
        else None
    )

    day_updated = None
    if decision:
        mutations.apply(db, plan.id, decision)
        if adaptation is not None:
            repo.add_adaptation_event(
                db,
                user.id,
                build_adaptation_log_entry(decision=adaptation, scheduled_sessions=scheduled_sessions),
            )
        reply_text = decision.fitmas_message
        extraction = Extraction(confidence=adaptation.event.confidence if adaptation else 0.85)
        day_updated = _resolve_day_updated(decision)
        logger.info("LLM reply (%s): %s", decision.mutation_type, reply_text[:120])
    elif calibration_only_reply is not None:
        extraction = Extraction(confidence=max(float(calibration_resolution.confidence or 0.0), 0.85))
        reply_text = calibration_only_reply
        logger.info("Calibration reply: %s", reply_text[:120])
    elif week_scope_reply is not None:
        extraction = Extraction(confidence=max(float(user_indication.confidence or 0.0), 0.85))
        reply_text = week_scope_reply
        logger.info("Week-scope reply: %s", reply_text[:120])
    elif no_candidate_reply is not None:
        extraction = Extraction(confidence=max(float(user_indication.confidence or 0.0), 0.85))
        reply_text = no_candidate_reply
        logger.info("No-candidate constraint reply: %s", reply_text[:120])
    elif execution_contestation_reply is not None:
        extraction = Extraction(confidence=max(float(conversation_context.non_completion_claim.confidence or 0.0), 0.88))
        reply_text = execution_contestation_reply
        logger.info("Execution contestation reply: %s", reply_text[:120])
    else:
        extraction = extract_reply(payload.text)
        fallback = generate_reply(payload.text, extraction)
        reply_text = fallback.assistant_message.text
        logger.info("Fallback reply: %s", reply_text[:120])

    repo.add_message(db, user.id, "agent", reply_text)
    extracted_facts = extract_facts(payload.text, reply_text, active_facts)
    if extracted_facts:
        _persist_memory_updates(db, user.id, extracted_facts)

        if not health_indication_handled:
            try:
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
