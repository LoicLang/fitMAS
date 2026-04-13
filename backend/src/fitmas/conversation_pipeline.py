from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.activity_claims import (
    build_claim_fact_payloads,
    build_execution_conflict_archive_payloads,
    build_non_completion_fact_payloads,
    format_activity_claim_for_prompt,
    format_non_completion_claim_for_prompt,
)
from fitmas.adaptation_log import build_adaptation_log_entry
from fitmas.calibration_llm import extract_calibration_resolution, generate_calibration_ack
from fitmas.calibration_needs import (
    build_resolution_memory_updates,
    find_open_calibration_need,
    is_standalone_calibration_answer,
    should_apply_calibration_resolution,
)
from fitmas.coach_state_bundle import build_coach_state_bundle
from fitmas.conversation_context import (
    activity_claim_summary_for_prompt,
    build_claim_memory_updates,
    build_conversation_context,
    execution_summary_for_prompt,
    non_completion_summary_for_prompt,
    signal_summary_for_prompt,
    temporal_summary_for_prompt,
)
from fitmas.conversation_contract import (
    ConversationPipelineDependencies,
    ConversationTurnInput,
    ConversationTurnOutcome,
    ConversationTurnState,
    ConversationUserNotFoundError,
)
from fitmas.models import Extraction, Message, MessageReply, MessageRole
from fitmas.mutation_permissions import (
    assess_mutation_impact,
    build_confirmation_followup,
    build_confirmation_prompt,
    build_rejection_reply,
    default_confirmation_expiry,
    deserialize_mutation_decision,
    parse_confirmation_reply,
    serialize_mutation_decision,
)
from fitmas.nlp import extract_reply, generate_reply
from fitmas.plan_mutation_service import apply_decisions_for_user
from fitmas.planning_window_resolution import resolve_planning_window
from fitmas.profile_summary import build_profile_summary
from fitmas.replan_from_life_change import (
    maybe_replan_from_life_change,
    maybe_replan_from_user_indication,
)
from fitmas.signals import collect_signals
from fitmas.tools.contract import ToolContext
from fitmas.user_indications import UserIndicationKind, supports_planning_resolution

logger = logging.getLogger(__name__)


def run_conversation_turn(
    payload: ConversationTurnInput,
    *,
    db: Session,
    dependencies: ConversationPipelineDependencies,
) -> MessageReply:
    import fitmas.api_messages as api_messages

    user = repo.get_user_optional(db)
    if user is None:
        raise ConversationUserNotFoundError("No onboarded user yet")

    state = _load_turn_state(db=db, user=user, user_text=payload.text)
    turn_memory_writes: list[dict] = []
    turn_context: dict[str, object] = {}
    pending_confirmation = repo.get_active_pending_mutation_confirmation(db, user.id)
    if pending_confirmation is not None:
        confirmation = parse_confirmation_reply(payload.text)
        if confirmation is None:
            normalized = api_messages._normalize_text(payload.text)
            if normalized in api_messages._ACK_TEXTS or normalized in api_messages._GREETING_TEXTS:
                reply_text = build_confirmation_followup()
                return _reply_and_record_turn(
                    db=db,
                    user_id=user.id,
                    user_text=payload.text,
                    reply_text=reply_text,
                    extraction=Extraction(confidence=0.95),
                    response_mode="confirmation_followup",
                    turn_context={"pending_confirmation": True, "pending_confirmation_id": pending_confirmation.id},
                    memory_writes=turn_memory_writes,
                )
            repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="superseded")
        elif confirmation is False:
            repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="rejected")
            reply_text = build_rejection_reply()
            decision = deserialize_mutation_decision(pending_confirmation.decision_json)
            return _reply_and_record_turn(
                db=db,
                user_id=user.id,
                user_text=payload.text,
                reply_text=reply_text,
                extraction=Extraction(confidence=0.98),
                response_mode="confirmation_rejected",
                decision=decision,
                turn_context={"pending_confirmation": True, "pending_confirmation_id": pending_confirmation.id},
                memory_writes=turn_memory_writes,
            )
        else:
            repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="accepted")
            decision = deserialize_mutation_decision(pending_confirmation.decision_json)
            service_result = apply_decisions_for_user(
                db,
                user=user,
                decisions=[decision],
                source="conversation",
                trigger_type="confirmation_accepted",
                explained_to_user=True,
            )
            applied = _mutation_was_applied(service_result)
            reply_text = (
                _applied_event_summary(service_result, decision)
                if applied
                else _blocked_mutation_reply(decision)
            )
            reply_text = api_messages._sanitize_no_change_reply(
                user_text=payload.text,
                reply_text=reply_text,
                decision=decision,
            )
            return _reply_and_record_turn(
                db=db,
                user_id=user.id,
                user_text=payload.text,
                reply_text=reply_text,
                extraction=Extraction(confidence=0.98),
                day_updated=api_messages._resolve_day_updated(decision) if applied else None,
                response_mode="confirmation_applied" if applied else "confirmation_blocked",
                decision=decision,
                mutation_applied=applied,
                turn_context={"pending_confirmation": True, "pending_confirmation_id": pending_confirmation.id},
                memory_writes=turn_memory_writes,
            )

    open_calibration_need = find_open_calibration_need(state.active_memory_rows)
    low_signal_reply = api_messages._maybe_low_signal_reply(
        payload.text,
        has_open_calibration_need=open_calibration_need is not None,
    )
    if low_signal_reply is not None:
        return _reply_and_record_turn(
            db=db,
            user_id=user.id,
            user_text=payload.text,
            reply_text=low_signal_reply,
            extraction=Extraction(confidence=0.95),
            response_mode="low_signal",
            turn_context={"low_signal": True},
            memory_writes=turn_memory_writes,
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
            _persist_turn_memory_updates(
                db,
                user.id,
                build_resolution_memory_updates(open_calibration_need, calibration_resolution),
                turn_memory_writes=turn_memory_writes,
            )
            state.active_memory_rows, state.active_facts = api_messages._active_memory_payloads(db, user.id)

    try:
        signals = collect_signals(db, user)
    except Exception:
        logger.exception("Failed to collect conversation signals")
        signals = []

    conversation_context = build_conversation_context(
        user_text=payload.text,
        conversation_history=state.conversation_history[:-1],
        timezone_name=user.timezone,
        scheduled_sessions=state.scheduled_sessions,
        activities=state.activities,
        active_facts=state.active_facts,
        signals=signals,
    )
    claim_summary = activity_claim_summary_for_prompt(conversation_context)
    non_completion_summary = non_completion_summary_for_prompt(conversation_context)
    if non_completion_summary:
        claim_summary = "\n".join(part for part in (claim_summary, non_completion_summary) if part)
    claim_facts = build_claim_memory_updates(
        conversation_context,
        activities=state.activities,
        timezone_name=user.timezone,
        user_text=payload.text,
    )
    if claim_facts:
        _persist_turn_memory_updates(db, user.id, claim_facts, turn_memory_writes=turn_memory_writes)
        state.active_memory_rows, state.active_facts = api_messages._active_memory_payloads(db, user.id)
        conversation_context = build_conversation_context(
            user_text=payload.text,
            conversation_history=state.conversation_history[:-1],
            timezone_name=user.timezone,
            scheduled_sessions=state.scheduled_sessions,
            activities=state.activities,
            active_facts=state.active_facts,
            signals=signals,
        )
        claim_summary = activity_claim_summary_for_prompt(conversation_context)
        non_completion_summary = non_completion_summary_for_prompt(conversation_context)
        if non_completion_summary:
            claim_summary = "\n".join(part for part in (claim_summary, non_completion_summary) if part)

    planning_decision = repo.get_latest_planning_decision_record(db, user.id)
    coach_bundle = build_coach_state_bundle(
        db,
        user=user,
        today_date=conversation_context.temporal_resolution.local_date,
        scheduled_sessions=state.scheduled_sessions,
        activities=state.activities,
        planning_decision=planning_decision,
        recent_adaptations_limit=4,
        screen="conversation",
    )
    profile_snapshot = coach_bundle.profile_snapshot
    clarification_target_session = api_messages._yesterday_target_session(
        db,
        user,
        today=conversation_context.temporal_resolution.local_date,
    )
    user_indication = dependencies.interpret_user_indication(
        payload.text,
        timezone_name=user.timezone,
        recent_agent_text=state.previous_agent_text,
        clarification_date=(
            api_messages._coerce_local_date(
                api_messages._value(clarification_target_session, "scheduled_date"),
                timezone_name=user.timezone,
            ).isoformat()
            if clarification_target_session is not None
            else None
        ),
        clarification_sport_type=(
            str(api_messages._value(clarification_target_session, "sport_type") or "").strip().lower() or None
        ),
    )
    resolved_non_completion_claim = (
        conversation_context.non_completion_claim or api_messages._resolved_non_completion_from_indication(user_indication)
    )
    resolved_activity_claim = (
        conversation_context.current_activity_claim or api_messages._resolved_activity_from_indication(user_indication)
    )

    supplemental_claim_payloads: list[dict] = []
    if conversation_context.current_activity_claim is None and resolved_activity_claim is not None:
        supplemental_claim_payloads.extend(
            build_claim_fact_payloads(
                resolved_activity_claim,
                activities=state.activities,
                timezone_name=user.timezone,
            )
        )
    if conversation_context.non_completion_claim is None and resolved_non_completion_claim is not None:
        supplemental_claim_payloads.extend(build_non_completion_fact_payloads(resolved_non_completion_claim))
    if supplemental_claim_payloads:
        _persist_turn_memory_updates(
            db,
            user.id,
            supplemental_claim_payloads,
            turn_memory_writes=turn_memory_writes,
        )
        state.active_memory_rows, state.active_facts = api_messages._active_memory_payloads(db, user.id)

    api_messages._apply_non_completion_resolution(
        db=db,
        user=user,
        scheduled_sessions=state.scheduled_sessions,
        timezone_name=user.timezone,
        non_completion_claim=resolved_non_completion_claim,
    )
    if resolved_non_completion_claim is not None:
        state.scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=21)
        state.timeline = [repo.to_pydantic_scheduled_session(session) for session in state.scheduled_sessions]
        state.today_session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    if conversation_context.current_activity_claim is None and resolved_activity_claim is not None:
        claim_summary = "\n".join(
            part for part in (claim_summary, format_activity_claim_for_prompt(resolved_activity_claim)) if part
        )
    if conversation_context.non_completion_claim is None and resolved_non_completion_claim is not None:
        claim_summary = "\n".join(
            part for part in (claim_summary, format_non_completion_claim_for_prompt(resolved_non_completion_claim)) if part
        )

    clarification = api_messages._targeted_execution_clarification(
        db=db,
        user=user,
        conversation_context=conversation_context,
        user_indication=user_indication,
        resolved_non_completion_claim=resolved_non_completion_claim,
        resolved_activity_claim=resolved_activity_claim,
        previous_agent_text=state.previous_agent_text,
    )
    if clarification is not None:
        reply_text = clarification.question
        return _reply_and_record_turn(
            db=db,
            user_id=user.id,
            user_text=payload.text,
            reply_text=reply_text,
            extraction=Extraction(confidence=0.9),
            response_mode="clarification",
            turn_context=turn_context,
            memory_writes=turn_memory_writes,
        )

    health_indication_facts = api_messages.build_health_fact_payloads_from_indication(user_indication)
    health_indication_handled = bool(health_indication_facts)
    if health_indication_facts:
        _persist_turn_memory_updates(
            db,
            user.id,
            health_indication_facts,
            turn_memory_writes=turn_memory_writes,
        )
        state.active_memory_rows, state.active_facts = api_messages._active_memory_payloads(db, user.id)

        health_result = dependencies.check_and_adapt_health_facts(
            db,
            user,
            health_indication_facts,
        )
        if health_result and health_result.applied and health_result.message:
            first_decision = health_result.decisions[0] if health_result.decisions else None
            extraction = Extraction(confidence=max(float(user_indication.confidence if user_indication else 0.0), 0.85))
            reply_text = health_result.message
            return _reply_and_record_turn(
                db=db,
                user_id=user.id,
                user_text=payload.text,
                reply_text=reply_text,
                extraction=extraction,
                day_updated=api_messages._resolve_day_updated(first_decision) if first_decision is not None else None,
                response_mode="health_adaptation",
                decision=first_decision,
                mutation_applied=bool(first_decision is not None),
                turn_context=turn_context,
                memory_writes=turn_memory_writes,
            )
        if health_result and health_result.decisions and health_result.message:
            first_decision = health_result.decisions[0]
            target_session = (
                repo.get_scheduled_session(db, user.id, first_decision.target_session_id)
                if first_decision.target_session_id is not None
                else None
            )
            impact = assess_mutation_impact(first_decision, target_session=target_session)
            if _can_auto_apply_health_suggestion(
                decision=first_decision,
                impact=impact,
                user_text=payload.text,
                normalize=api_messages._normalize_text,
            ):
                service_result = apply_decisions_for_user(
                    db,
                    user=user,
                    decisions=[first_decision],
                    source="conversation",
                    trigger_type="health_adaptation",
                    explained_to_user=True,
                )
                reply_text = _applied_event_summary(service_result, first_decision) or health_result.message
                return _reply_and_record_turn(
                    db=db,
                    user_id=user.id,
                    user_text=payload.text,
                    reply_text=reply_text,
                    extraction=Extraction(confidence=max(float(user_indication.confidence if user_indication else 0.0), 0.85)),
                    day_updated=api_messages._resolve_day_updated(first_decision),
                    response_mode="health_adaptation",
                    decision=first_decision,
                    mutation_applied=bool(service_result and service_result.applied_count > 0),
                    turn_context=turn_context,
                    memory_writes=turn_memory_writes,
                )
            pending_row = repo.create_pending_mutation_confirmation(
                db,
                user_id=user.id,
                impact_level=impact.level,
                reason=impact.reason,
                mutation_type=first_decision.mutation_type,
                summary=impact.summary,
                source_text=payload.text,
                decision_json=serialize_mutation_decision(first_decision),
                expires_at=default_confirmation_expiry(),
            )
            reply_text = build_confirmation_prompt(first_decision, assessment=impact)
            return _reply_and_record_turn(
                db=db,
                user_id=user.id,
                user_text=payload.text,
                reply_text=reply_text,
                extraction=Extraction(confidence=max(float(user_indication.confidence if user_indication else 0.0), 0.85)),
                day_updated=api_messages._resolve_day_updated(first_decision),
                response_mode="mutation_confirmation",
                decision=first_decision,
                pending_confirmation=True,
                pending_confirmation_id=pending_row.id,
                turn_context=turn_context,
                memory_writes=turn_memory_writes,
            )

    adaptation = maybe_replan_from_life_change(
        user_text=payload.text,
        today=conversation_context.temporal_resolution.local_date,
        time_context=conversation_context.time_context,
        profile=profile_snapshot,
        week_plan=None,
        planning_decision=planning_decision,
        today_session=state.today_session,
        scheduled_sessions=state.scheduled_sessions,
    )
    swap_request = api_messages._looks_like_swap_request(payload.text)
    if (
        adaptation is None
        and user_indication is not None
        and supports_planning_resolution(user_indication)
        and not swap_request
    ):
        resolution = resolve_planning_window(
            indication=user_indication,
            scheduled_sessions=state.scheduled_sessions,
            timezone_name=user.timezone,
        )
        adaptation = maybe_replan_from_user_indication(
            indication=user_indication,
            resolution=resolution,
            today=conversation_context.temporal_resolution.local_date,
            profile=profile_snapshot,
            week_plan=None,
            planning_decision=planning_decision,
            today_session=state.today_session,
            scheduled_sessions=state.scheduled_sessions,
        )
    else:
        resolution = None

    standalone_calibration_answer = (
        open_calibration_need is not None
        and should_apply_calibration_resolution(calibration_resolution)
        and adaptation is None
        and is_standalone_calibration_answer(payload.text)
    )

    week_scope_reply = None
    no_candidate_reply = None
    if (
        adaptation is None
        and not standalone_calibration_answer
        and user_indication is not None
        and user_indication.kind is UserIndicationKind.AVAILABILITY_CONSTRAINT
        and not swap_request
    ):
        if resolution is None and user_indication.time_reference is not None:
            resolution = resolve_planning_window(
                indication=user_indication,
                scheduled_sessions=state.scheduled_sessions,
                timezone_name=user.timezone,
            )
        no_candidate_reply = api_messages._no_candidate_constraint_reply(user_indication, resolution)
        week_scope_reply = api_messages._week_scope_reply(user_indication, resolution)

    calibration_only_reply = None
    execution_contestation_reply = api_messages._execution_contestation_reply(
        db=db,
        user=user,
        scheduled_sessions=state.scheduled_sessions,
        activities=state.activities,
        timezone_name=user.timezone,
        non_completion_claim=resolved_non_completion_claim,
    )
    if standalone_calibration_answer:
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
    turn_context = {
        "profile_summary": build_profile_summary(state.active_memory_rows),
        "timeline_summary": api_messages.make_timeline_summary(state.timeline),
        "execution_summary": execution_summary_for_prompt(conversation_context),
        "temporal_summary": temporal_summary_for_prompt(conversation_context),
        "activity_claim_summary": claim_summary,
        "signal_summary": signal_summary_for_prompt(conversation_context),
        "history_messages": max(len(state.conversation_history) - 1, 0),
        "selected_fact_keys": [
            _fact_identity(fact)
            for fact in (list(conversation_context.selected_facts) or [])[:6]
        ],
        "user_indication_kind": user_indication.kind.value if user_indication is not None else None,
        "planning_contract": coach_bundle.planning_contract.as_dict(),
        "availability_state": coach_bundle.availability_state.as_dict(),
        "week_mission": coach_bundle.week_mission.as_dict(),
        "recent_reality": coach_bundle.recent_reality.as_dict(),
        "last_adaptation": coach_bundle.latest_adaptation.as_dict() if coach_bundle.latest_adaptation is not None else None,
        "week_context": {
            "summary": coach_bundle.week_summary,
            "planning": coach_bundle.planning_context,
            "next_week": coach_bundle.next_week,
            "coach_reading": coach_bundle.coach_reading,
        },
    }

    decision = (
        dependencies.decide(
            payload.text,
            "",
            timeline_summary=api_messages.make_timeline_summary(state.timeline),
            execution_summary=execution_summary_for_prompt(conversation_context),
            temporal_summary=temporal_summary_for_prompt(conversation_context),
            activity_claim_summary=claim_summary,
            signal_summary=signal_summary_for_prompt(conversation_context),
            conversation_history=state.conversation_history[:-1],
            coach_context={
                "coach_name": user.coach_name,
                "coach_style": user.coach_style,
                "coach_relationship": user.coach_relationship,
                "coach_do": user.coach_do,
                "coach_dont": user.coach_dont,
                "coach_soul": user.coach_soul,
                "timezone": user.timezone,
                "today_session_id": state.today_session.id if state.today_session else None,
                "profile_summary": build_profile_summary(state.active_memory_rows),
                "selected_facts": list(conversation_context.selected_facts) or api_messages.select_prompt_facts(state.active_facts),
                "planning_contract": coach_bundle.planning_contract.as_dict(),
                "availability_state": coach_bundle.availability_state.as_dict(),
                "week_mission": coach_bundle.week_mission.as_dict(),
                "recent_reality": coach_bundle.recent_reality.as_dict(),
                "last_adaptation": coach_bundle.latest_adaptation.as_dict() if coach_bundle.latest_adaptation is not None else None,
                "week_context": {
                    "summary": coach_bundle.week_summary,
                    "planning": coach_bundle.planning_context,
                    "next_week": coach_bundle.next_week,
                    "coach_reading": coach_bundle.coach_reading,
                },
            },
            remembered_facts=state.active_facts,
            time_context=conversation_context.time_context,
            tool_context=ToolContext(
                pipeline="conversation",
                user_id=user.id,
                timezone_name=user.timezone,
                scheduled_sessions=state.scheduled_sessions,
                activities=state.activities,
                active_facts=state.active_facts,
            ),
        )
        if adaptation is None
        and calibration_only_reply is None
        and week_scope_reply is None
        and no_candidate_reply is None
        and execution_contestation_reply is None
        else (
            api_messages._to_mutation_decision(adaptation.selected_scenario.mutation, fitmas_message=adaptation.user_message)
            if adaptation is not None
            else None
        )
    )

    if decision:
        target_session = (
            repo.get_scheduled_session(db, user.id, decision.target_session_id)
            if decision.target_session_id is not None
            else None
        )
        second_session = (
            repo.get_scheduled_session(db, user.id, decision.second_session_id)
            if decision.second_session_id is not None
            else None
        )
        impact = assess_mutation_impact(
            decision,
            target_session=target_session,
            second_session=second_session,
        )
        if impact.requires_confirmation:
            pending_row = repo.create_pending_mutation_confirmation(
                db,
                user_id=user.id,
                impact_level=impact.level,
                reason=impact.reason,
                mutation_type=decision.mutation_type,
                summary=impact.summary,
                source_text=payload.text,
                decision_json=serialize_mutation_decision(decision),
                expires_at=default_confirmation_expiry(),
            )
            reply_text = build_confirmation_prompt(decision, assessment=impact)
            outcome = ConversationTurnOutcome(
                extraction=Extraction(confidence=adaptation.event.confidence if adaptation else 0.85),
                reply_text=reply_text,
                response_mode="mutation_confirmation",
                decision=decision,
                pending_confirmation=True,
                pending_confirmation_id=pending_row.id,
            )
            logger.info("Pending confirmation (%s): %s", decision.mutation_type, reply_text[:120])
        elif decision.mutation_type == "no_change":
            reply_text = api_messages._sanitize_no_change_reply(
                user_text=payload.text,
                reply_text=decision.fitmas_message,
                decision=decision,
            )
            outcome = ConversationTurnOutcome(
                extraction=Extraction(confidence=adaptation.event.confidence if adaptation else 0.85),
                reply_text=reply_text,
                response_mode="reply",
                decision=decision,
                mutation_applied=False,
            )
            logger.info("LLM reply (%s): %s", decision.mutation_type, reply_text[:120])
        else:
            service_result = apply_decisions_for_user(
                db,
                user=user,
                decisions=[decision],
                source="conversation",
                trigger_type="life_change_adaptation" if adaptation is not None else "message",
                explained_to_user=True,
            )
            if adaptation is not None:
                repo.add_adaptation_event(
                    db,
                    user.id,
                    build_adaptation_log_entry(decision=adaptation, scheduled_sessions=state.scheduled_sessions),
                )
            applied = _mutation_was_applied(service_result)
            reply_text = (
                _applied_event_summary(service_result, decision)
                if applied
                else _blocked_mutation_reply(decision)
            )
            reply_text = api_messages._sanitize_no_change_reply(
                user_text=payload.text,
                reply_text=reply_text,
                decision=decision,
            )
            outcome = ConversationTurnOutcome(
                extraction=Extraction(confidence=adaptation.event.confidence if adaptation else 0.85),
                reply_text=reply_text,
                day_updated=api_messages._resolve_day_updated(decision) if applied else None,
                response_mode="mutation_applied" if applied else "mutation_blocked",
                decision=decision,
                mutation_applied=applied,
            )
            logger.info("LLM reply (%s): %s", decision.mutation_type, reply_text[:120])
    elif calibration_only_reply is not None:
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=max(float(calibration_resolution.confidence or 0.0), 0.85)),
            reply_text=calibration_only_reply,
            response_mode="calibration",
        )
        logger.info("Calibration reply: %s", outcome.reply_text[:120])
    elif week_scope_reply is not None:
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=max(float(user_indication.confidence or 0.0), 0.85)),
            reply_text=week_scope_reply,
            response_mode="week_scope",
        )
        logger.info("Week-scope reply: %s", outcome.reply_text[:120])
    elif no_candidate_reply is not None:
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=max(float(user_indication.confidence or 0.0), 0.85)),
            reply_text=no_candidate_reply,
            response_mode="no_candidate",
        )
        logger.info("No-candidate constraint reply: %s", outcome.reply_text[:120])
    elif execution_contestation_reply is not None:
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=max(float(resolved_non_completion_claim.confidence or 0.0), 0.88)),
            reply_text=execution_contestation_reply,
            response_mode="execution_contestation",
        )
        logger.info("Execution contestation reply: %s", outcome.reply_text[:120])
    else:
        extraction = extract_reply(payload.text)
        fallback = generate_reply(payload.text, extraction)
        outcome = ConversationTurnOutcome(
            extraction=extraction,
            reply_text=fallback.assistant_message.text,
            response_mode="fallback",
        )
        logger.info("Fallback reply: %s", outcome.reply_text[:120])
    extracted_facts = dependencies.extract_facts(payload.text, outcome.reply_text, state.active_facts)
    extracted_facts.extend(
        build_execution_conflict_archive_payloads(
            state.active_facts,
            activity_claim=resolved_activity_claim,
            non_completion_claim=resolved_non_completion_claim,
        )
    )
    if extracted_facts:
        _persist_turn_memory_updates(
            db,
            user.id,
            extracted_facts,
            turn_memory_writes=turn_memory_writes,
        )
        if not health_indication_handled and api_messages._should_run_post_reply_health_adaptation(
            user_text=payload.text,
            extracted_facts=extracted_facts,
            user_indication=user_indication,
        ):
            try:
                health_result = dependencies.check_and_adapt_health_facts(db, user, extracted_facts)
                if health_result and health_result.applied and health_result.message:
                    repo.add_message(db, user.id, "agent", health_result.message)
            except Exception:
                logger.exception("Adaptation health_fact check failed (non-blocking)")

    return _reply_and_record_turn(
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


def _load_turn_state(*, db: Session, user, user_text: str) -> ConversationTurnState:
    repo.add_message(db, user.id, "user", user_text)
    logger.info("User message: %s", user_text[:120])

    msgs = repo.get_messages(db, user.id)
    conversation_history = [{"role": msg.role, "text": msg.text} for msg in msgs]
    previous_agent_text = _latest_agent_text(conversation_history[:-1])
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=21)
    timeline = [repo.to_pydantic_scheduled_session(session) for session in scheduled_sessions]
    activities = repo.get_activities(db, user.id, limit=120)
    today_session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    active_memory_rows, active_facts = _active_memory_payloads(db, user.id)
    return ConversationTurnState(
        user=user,
        conversation_history=conversation_history,
        previous_agent_text=previous_agent_text,
        scheduled_sessions=scheduled_sessions,
        timeline=timeline,
        activities=activities,
        today_session=today_session,
        active_memory_rows=active_memory_rows,
        active_facts=active_facts,
    )


def _active_memory_payloads(db: Session, user_id: int) -> tuple[list[object], list[dict]]:
    import fitmas.api_messages as api_messages

    return api_messages._active_memory_payloads(db, user_id)


def _can_auto_apply_health_suggestion(*, decision, impact, user_text: str, normalize) -> bool:
    if impact.requires_confirmation:
        return False
    if decision.mutation_type == "lighten_day":
        return True
    if decision.mutation_type != "replace_session":
        return False
    normalized = normalize(user_text)
    fatigue_markers = ("fatigue", "rince", "jambes lourdes", "creve", "epuise")
    pain_markers = ("douleur", "mal ", "blesse", "blessure", "gene")
    return any(marker in normalized for marker in fatigue_markers) and not any(
        marker in normalized for marker in pain_markers
    )


def _applied_event_summary(service_result, decision) -> str | None:
    if service_result is None:
        return None
    for event in getattr(service_result, "applied_events", ()):
        if event.command_type == decision.mutation_type:
            return event.user_visible_summary
    return None


def _mutation_was_applied(service_result) -> bool:
    if service_result is None:
        return False
    return int(getattr(service_result, "applied_count", 0) or 0) > 0 and int(
        getattr(service_result, "event_count", 0) or 0
    ) > 0


def _blocked_mutation_reply(decision) -> str:
    if getattr(decision, "mutation_type", "") == "move_session":
        return (
            "Je ne l'ai pas applique: le creneau cible n'est pas assez sur. "
            "Si tu veux echanger deux seances, donne-moi les deux seances ou les deux jours."
        )
    return "Je ne l'ai pas applique: le changement n'a pas ete valide par le planning."


def _latest_agent_text(conversation_history: list[dict]) -> str | None:
    import fitmas.api_messages as api_messages

    return api_messages._latest_agent_text(conversation_history)


def _persist_turn_memory_updates(
    db: Session,
    user_id: int,
    payloads: list[dict],
    *,
    turn_memory_writes: list[dict],
) -> None:
    import fitmas.api_messages as api_messages

    if not payloads:
        return
    api_messages._persist_memory_updates(db, user_id, payloads)
    turn_memory_writes.extend(dict(payload) for payload in payloads)


def _reply_and_record_turn(
    *,
    db: Session,
    user_id: int,
    user_text: str,
    reply_text: str,
    extraction: Extraction,
    response_mode: str,
    day_updated=None,
    decision=None,
    mutation_applied: bool = False,
    pending_confirmation: bool = False,
    pending_confirmation_id: int | None = None,
    turn_context: dict[str, object] | None = None,
    memory_writes: list[dict] | None = None,
) -> MessageReply:
    repo.add_message(db, user_id, "agent", reply_text)
    repo.add_conversation_turn(
        db,
        user_id=user_id,
        user_message=user_text,
        assistant_message=reply_text,
        response_mode=response_mode,
        extraction_confidence=float(extraction.confidence or 0.0),
        day_updated=getattr(day_updated, "value", day_updated),
        mutation_type=str(getattr(decision, "mutation_type", "") or ""),
        mutation_applied=mutation_applied,
        pending_confirmation=pending_confirmation,
        pending_confirmation_id=pending_confirmation_id,
        decision_json=serialize_mutation_decision(decision) if decision is not None else "{}",
        context=turn_context,
        memory_writes=memory_writes,
    )
    return MessageReply(
        user_message=Message(role=MessageRole.USER, text=user_text),
        extraction=extraction,
        assistant_message=Message(role=MessageRole.AGENT, text=reply_text),
        day_updated=day_updated,
    )


def _fact_identity(fact: object) -> str:
    if isinstance(fact, dict):
        return f"{fact.get('category')}:{fact.get('key')}"
    return str(fact)
