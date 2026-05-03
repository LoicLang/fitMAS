from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from fitmas import final_reply, repository as repo
from fitmas.adaptation_log import build_adaptation_log_entry
from fitmas.calibration_llm import extract_calibration_resolution
from fitmas import coach_voice
from fitmas import llm_gateway as gw
from fitmas.claim_guard import (
    build_claim_repair_prompt,
    looks_like_action_claim,
    outage_fallback_reply,
)
from fitmas.calibration_needs import (
    build_resolution_memory_updates,
    find_open_calibration_need,
    should_apply_calibration_resolution,
)
from fitmas.coach_reading_digest import build_coach_reading_digest, render_digest_for_prompt
from fitmas.coach_state_bundle import build_coach_state_bundle
from fitmas.execution_clarification import render_unresolved_execution_followup
from fitmas.llm import MutationDecision
from fitmas.execution_mutation_service import apply_execution_actions_for_user
from fitmas.memory_mutation_service import apply_memory_actions_for_user
from fitmas.conversation_context import (
    activity_claim_summary_for_prompt,
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
    build_confirmation_prompt,
    default_confirmation_expiry,
    deserialize_mutation_decision,
    deserialize_plan_patch_confirmation,
    serialize_plan_patch_confirmation,
    serialize_mutation_decision,
)
from fitmas.plan_mutation_service import PlanPatchServiceResult, apply_decisions_for_user, apply_patch_for_user
from fitmas.plan_patch import validate_plan_patch
from fitmas.profile_summary import build_profile_summary
from fitmas.signals import collect_signals
from fitmas.tools.contract import ToolContext

logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger("fitmas.conversation_metrics")


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
    pending_confirmation_context = _pending_confirmation_context_for_prompt(pending_confirmation)

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
    turn_plan = dependencies.plan_turn(
        user_text=payload.text,
        temporal_summary=temporal_summary_for_prompt(conversation_context),
        execution_summary=execution_summary_for_prompt(conversation_context),
        activity_claim_summary=claim_summary,
        signal_summary=signal_summary_for_prompt(conversation_context),
    )
    if turn_plan is None:
        llm_plan_mutation_request = False
    else:
        llm_plan_mutation_request = bool(getattr(turn_plan, "has_plan_mutation", False))
    plan_mutation_request = bool(llm_plan_mutation_request)

    # Targeted execution clarification: previously short-circuited the pipeline
    # with a canned "Tu l'as faite ou pas ?" reply, which loops on missed
    # sessions and bypasses decide(). We now surface it as soft prompt context
    # — the LLM arbitrates whether to ask, integrate or move on based on the
    # user's actual message this turn. The anti-spam guard
    # (looks_like_execution_clarification_prompt on previous_agent_text) is
    # preserved inside _targeted_execution_clarification, so a follow-up turn
    # gets no block injected and the loop breaks.
    clarification = (
        None
        if plan_mutation_request
        else api_messages._targeted_execution_clarification(
            db=db,
            user=user,
            conversation_context=conversation_context,
            previous_agent_text=state.previous_agent_text,
        )
    )
    unresolved_execution_followup_text: str | None = None
    if clarification is not None:
        yesterday = conversation_context.temporal_resolution.local_date.fromordinal(
            conversation_context.temporal_resolution.local_date.toordinal() - 1
        )
        unresolved_execution_followup_text = render_unresolved_execution_followup(
            clarification,
            target_date_iso=yesterday.isoformat(),
        )

    adaptation = None
    route_adaptation_context_to_llm = _should_route_adaptation_context_to_llm(
        turn_plan,
        adaptation,
        plan_mutation_request=plan_mutation_request,
    )

    week_scope_reply = None
    no_candidate_reply = None
    route_availability_context_to_llm = _should_route_availability_context_to_llm(
        turn_plan,
        week_scope_reply=week_scope_reply,
        no_candidate_reply=no_candidate_reply,
    )
    grounding_prompt_context = _append_prompt_section(
        (
            _availability_context_for_prompt(
                week_scope_reply=week_scope_reply,
                no_candidate_reply=no_candidate_reply,
            )
            if route_availability_context_to_llm
            else None
        )
        or "",
        _adaptation_context_for_prompt(adaptation) if route_adaptation_context_to_llm else None,
    )
    grounding_prompt_context = _append_prompt_section(
        grounding_prompt_context,
        pending_confirmation_context,
    )
    decision_temporal_summary = _append_prompt_section(
        temporal_summary_for_prompt(conversation_context),
        grounding_prompt_context,
    )
    decision_signal_summary = _append_prompt_section(
        signal_summary_for_prompt(conversation_context),
        grounding_prompt_context,
    )

    turn_context = {
        "profile_summary": build_profile_summary(state.active_memory_rows),
        "timeline_summary": api_messages.make_timeline_summary(state.timeline),
        "execution_summary": execution_summary_for_prompt(conversation_context),
        "temporal_summary": decision_temporal_summary,
        "activity_claim_summary": claim_summary,
        "signal_summary": decision_signal_summary,
        "history_messages": max(len(state.conversation_history) - 1, 0),
        "selected_fact_keys": [
            _fact_identity(fact)
            for fact in (list(conversation_context.selected_facts) or [])[:6]
        ],
        "turn_plan": _turn_plan_payload(turn_plan),
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

    # Chantier 1 (autonomy refactor): decide() runs on every conversational
    # turn that is not a calibration-only ack. The deterministic groundings
    # (availability, adaptation, execution contestation, low-signal) are
    # exposed as prompt context, never as final replies.
    decision = dependencies.decide(
        payload.text,
        "",
        timeline_summary=api_messages.make_timeline_summary(state.timeline),
        execution_summary=execution_summary_for_prompt(conversation_context),
        temporal_summary=decision_temporal_summary,
        activity_claim_summary=claim_summary,
        signal_summary=decision_signal_summary,
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
            "turn_primary_intent": getattr(turn_plan, "primary_intent", None),
            "turn_secondary_intents": list(getattr(turn_plan, "secondary_intents", ()) or ()),
            "profile_summary": build_profile_summary(state.active_memory_rows),
            "selected_facts": _selected_facts_for_prompt(conversation_context, state.active_facts),
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
            "coach_reading_digest_text": _maybe_build_coach_reading_digest_text(
                db,
                user=user,
                today=conversation_context.temporal_resolution.local_date,
                recent_reality_window=coach_bundle.recent_reality,
                turn_plan=turn_plan,
            ),
            "unresolved_execution_followup": unresolved_execution_followup_text,
        },
        remembered_facts=state.active_facts,
        time_context=conversation_context.time_context,
        tool_context=ToolContext(
            pipeline="conversation",
            user_id=user.id,
            timezone_name=user.timezone,
            db=db,
            scheduled_sessions=state.scheduled_sessions,
            activities=state.activities,
            active_facts=state.active_facts,
        ),
    )
    outcome: ConversationTurnOutcome | None = None
    if _is_coach_decision(decision):
        turn_context["coach_decision"] = _coach_decision_payload(decision)
        turn_context["coach_decision_action_result"] = _apply_coach_decision_actions(
            db=db,
            user=user,
            decision=decision,
            turn_memory_writes=turn_memory_writes,
            unresolved_execution_followup=unresolved_execution_followup_text,
        )
        pending_outcome = _apply_pending_resolution(
            db=db,
            user=user,
            decision=decision,
            pending_confirmation=pending_confirmation,
        )
        if pending_outcome is not None:
            outcome = pending_outcome
            decision = None
        elif decision.response_type == "mutation_decision" and decision.mutation_decision is not None:
            decision = decision.mutation_decision
        elif decision.response_type == "requires_confirmation" and decision.plan_patch is not None:
            validation = validate_plan_patch(
                db,
                plan_id=0,
                patch=decision.plan_patch,
                scheduled_sessions=state.scheduled_sessions,
                timezone_name=user.timezone,
            )
            service_result = PlanPatchServiceResult(validation=validation)
            if validation.status == "blocked":
                reply_text = _blocked_plan_patch_reply(service_result)
                _log_plan_patch_blocked(service_result, user_id=user.id)
                outcome = ConversationTurnOutcome(
                    extraction=Extraction(confidence=0.85),
                    reply_text=reply_text,
                    response_mode="plan_patch_blocked",
                    mutation_applied=False,
                )
            else:
                pending_row = repo.create_pending_mutation_confirmation(
                    db,
                    user_id=user.id,
                    impact_level="high",
                    reason=decision.confirmation_reason or "llm_requires_confirmation",
                    mutation_type="plan_patch",
                    summary=_plan_patch_confirmation_summary(service_result),
                    source_text=payload.text,
                    decision_json=serialize_plan_patch_confirmation(decision.plan_patch),
                    expires_at=default_confirmation_expiry(),
                )
                reply_text = _build_plan_patch_confirmation_prompt(service_result)
                outcome = ConversationTurnOutcome(
                    extraction=Extraction(confidence=0.85),
                    reply_text=reply_text,
                    response_mode="plan_patch_confirmation",
                    pending_confirmation=True,
                    pending_confirmation_id=pending_row.id,
                )
            decision = None
        elif decision.response_type == "plan_patch" and decision.plan_patch is not None:
            service_result = apply_patch_for_user(
                db,
                user=user,
                patch=decision.plan_patch,
                source="conversation",
                trigger_type="coach_decision_plan_patch",
                explained_to_user=True,
            )
            applied = _patch_was_applied(service_result)
            if applied:
                reply_text = _applied_plan_patch_reply(service_result, fallback=decision.plan_patch.coach_message)
                outcome = ConversationTurnOutcome(
                    extraction=Extraction(confidence=0.85),
                    reply_text=reply_text,
                    response_mode="plan_patch_applied",
                    mutation_applied=True,
                )
            elif _plan_patch_needs_confirmation(service_result):
                pending_row = repo.create_pending_mutation_confirmation(
                    db,
                    user_id=user.id,
                    impact_level="high",
                    reason="plan_patch_requires_confirmation",
                    mutation_type="plan_patch",
                    summary=_plan_patch_confirmation_summary(service_result),
                    source_text=payload.text,
                    decision_json=serialize_plan_patch_confirmation(decision.plan_patch),
                    expires_at=default_confirmation_expiry(),
                )
                reply_text = _build_plan_patch_confirmation_prompt(service_result)
                outcome = ConversationTurnOutcome(
                    extraction=Extraction(confidence=0.85),
                    reply_text=reply_text,
                    response_mode="plan_patch_confirmation",
                    pending_confirmation=True,
                    pending_confirmation_id=pending_row.id,
                )
            else:
                action_result = turn_context.get("coach_decision_action_result") or {}
                if int(action_result.get("execution_applied") or 0) > 0:
                    reply_text = _execution_applied_patch_blocked_reply(
                        db,
                        user=user,
                        action_result=action_result,
                        service_result=service_result,
                    )
                else:
                    reply_text = _blocked_plan_patch_reply(service_result)
                _log_plan_patch_blocked(service_result, user_id=user.id)
                outcome = ConversationTurnOutcome(
                    extraction=Extraction(confidence=0.85),
                    reply_text=reply_text,
                    response_mode="plan_patch_blocked",
                    mutation_applied=False,
                )
            logger.info("LLM coach patch reply (%s): %s", outcome.response_mode, reply_text[:120])
            decision = None
        else:
            reply_text = decision.confirmation_reason or decision.fitmas_message
            legacy_no_change = MutationDecision(
                mutation_type="no_change",
                rationale=decision.rationale,
                fitmas_message=reply_text,
            )
            outcome = ConversationTurnOutcome(
                extraction=Extraction(confidence=0.85),
                reply_text=reply_text,
                response_mode=decision.response_type,
                decision=legacy_no_change,
                mutation_applied=False,
            )
            decision = None

    if outcome is None and decision:
        extraction_confidence = adaptation.event.confidence if adaptation else 0.85
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
                extraction=Extraction(confidence=extraction_confidence),
                reply_text=reply_text,
                response_mode="mutation_confirmation",
                decision=decision,
                pending_confirmation=True,
                pending_confirmation_id=pending_row.id,
            )
            logger.info("Pending confirmation (%s): %s", decision.mutation_type, reply_text[:120])
        elif decision.mutation_type == "no_change":
            outcome = ConversationTurnOutcome(
                extraction=Extraction(confidence=extraction_confidence),
                reply_text=decision.fitmas_message,
                response_mode="reply",
                decision=decision,
                mutation_applied=False,
            )
            logger.info("LLM reply (%s): %s", decision.mutation_type, decision.fitmas_message[:120])
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
                else _blocked_mutation_reply(decision, service_result)
            )
            if not applied:
                _log_mutation_blocked(service_result, user_id=user.id)
            outcome = ConversationTurnOutcome(
                extraction=Extraction(confidence=extraction_confidence),
                reply_text=reply_text,
                day_updated=api_messages._resolve_day_updated(decision) if applied else None,
                response_mode="mutation_applied" if applied else "mutation_blocked",
                decision=decision,
                mutation_applied=applied,
            )
            logger.info("LLM reply (%s): %s", decision.mutation_type, reply_text[:120])
    elif outcome is None:
        # Chantier 1 (autonomy refactor): the only remaining path here is
        # "decide() returned None and there is no deterministic adaptation
        # to fall back on" — typically the Anthropic client is unavailable.
        # Reply soberly: do not assert any plan state, do not regurgitate
        # rule-based phrases that could lie about the situation.
        logger.warning("conversation_pipeline: decide() returned None with no fallback decision")
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=0.5),
            reply_text="Je ne peux pas te repondre tout de suite. Reessaie dans un instant.",
            response_mode="llm_unavailable",
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

    extracted_facts = dependencies.extract_facts(payload.text, outcome.reply_text, state.active_facts)
    if extracted_facts:
        _persist_turn_memory_updates(
            db,
            user.id,
            extracted_facts,
            turn_memory_writes=turn_memory_writes,
        )

    if (
        pending_confirmation is not None
        and pending_confirmation.status == "pending"
        and outcome.response_mode != "llm_unavailable"
    ):
        repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="superseded")

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


def _pending_confirmation_context_for_prompt(pending_confirmation) -> str | None:
    if pending_confirmation is None:
        return None
    return (
        "Confirmation planning en attente (artefact machine, pas une decision deja appliquee):\n"
        f"- id: {pending_confirmation.id}\n"
        f"- type: {pending_confirmation.mutation_type}\n"
        f"- raison: {pending_confirmation.reason}\n"
        f"- resume: {pending_confirmation.summary}\n"
        "- lis le nouveau message dans ce contexte et decide toi-meme.\n"
        "- si le user accepte clairement, retourne `pending_resolution.type=accept_pending`.\n"
        "- si le user refuse, retourne `pending_resolution.type=reject_pending`.\n"
        "- si le user modifie la demande, retourne `modify_pending` avec requested_changes; ne forge pas un nouveau patch libre.\n"
        "- si le user parle d'autre chose, retourne `ignore` et reponds au nouveau message.\n"
        f"- payload: {pending_confirmation.decision_json}\n"
    )


def _applied_event_summary(service_result, decision) -> str | None:
    if service_result is None:
        return None
    for event in getattr(service_result, "applied_events", ()):
        if event.command_type == decision.mutation_type:
            return event.user_visible_summary
    return None


def _log_mutation_blocked(service_result, *, user_id: int | None) -> None:
    """Emit a structured log per blocked mutation so dogfood logs can be
    grepped by reason. Silent when there are no blocked events (e.g. the
    mutation was a no-op rather than a pre-hook rejection)."""
    if service_result is None:
        return
    for event in getattr(service_result, "blocked_events", ()) or ():
        logger.warning(
            "mutation_blocked user=%s command=%s reason=%s target=%s second=%s",
            user_id,
            event.command_type,
            event.block_reason,
            event.target_session_id,
            event.second_session_id,
        )


def _mutation_was_applied(service_result) -> bool:
    if service_result is None:
        return False
    return int(getattr(service_result, "applied_count", 0) or 0) > 0 and int(
        getattr(service_result, "event_count", 0) or 0
    ) > 0


def _is_coach_decision(value: Any) -> bool:
    return bool(
        value is not None
        and hasattr(value, "response_type")
        and hasattr(value, "fitmas_message")
    )


def _coach_decision_payload(decision: Any) -> dict[str, Any]:
    if hasattr(decision, "model_dump"):
        return dict(decision.model_dump(mode="json"))
    return {
        "response_type": getattr(decision, "response_type", None),
        "rationale": getattr(decision, "rationale", None),
        "fitmas_message": getattr(decision, "fitmas_message", None),
    }


def _apply_coach_decision_actions(
    *,
    db: Session,
    user,
    decision: Any,
    turn_memory_writes: list[dict],
    unresolved_execution_followup: str | None = None,
) -> dict[str, int]:
    memory_actions = tuple(getattr(decision, "memory_actions", ()) or ())
    execution_actions = tuple(getattr(decision, "execution_actions", ()) or ())
    pending_resolution = getattr(decision, "pending_resolution", None)
    memory_result = None
    execution_result = None
    if memory_actions:
        memory_result = apply_memory_actions_for_user(
            db,
            user=user,
            actions=memory_actions,
            source="coach_decision",
        )
        for key in memory_result.saved_keys:
            category, _, item_key = key.partition(":")
            turn_memory_writes.append(
                {
                    "category": category or "memory",
                    "key": item_key or key,
                    "source": "coach_decision",
                    "action": "applied",
                }
            )
    if execution_actions:
        execution_result = apply_execution_actions_for_user(
            db,
            user=user,
            actions=execution_actions,
            source="coach_decision",
        )
        for session_id in execution_result.updated_session_ids:
            turn_memory_writes.append(
                {
                    "category": "execution",
                    "key": "record_execution_update",
                    "value": f"session_id={session_id}",
                    "source": "coach_decision",
                    "action": "applied",
                }
            )
        if execution_result.blocked_count:
            turn_memory_writes.append(
                {
                    "category": "execution",
                    "key": "record_execution_update",
                    "value": f"blocked={execution_result.blocked_count}",
                    "source": "coach_decision",
                    "action": "blocked",
                }
            )
    metric_payload = {
        "memory_applied": int(getattr(memory_result, "applied_count", 0) or 0),
        "memory_blocked": int(getattr(memory_result, "blocked_count", 0) or 0),
        "execution_applied": int(getattr(execution_result, "applied_count", 0) or 0),
        "execution_blocked": int(getattr(execution_result, "blocked_count", 0) or 0),
        "execution_updated_session_ids": tuple(getattr(execution_result, "updated_session_ids", ()) or ()),
    }
    missing_execution_action = bool(unresolved_execution_followup and not execution_actions)
    metrics_logger.info(
        "conversation_action_metrics user=%s memory_actions_per_turn=%s execution_actions_per_turn=%s pending_resolution_per_turn=%s llm_understanding_missing_action=%s memory_applied=%s execution_applied=%s",
        getattr(user, "id", None),
        len(memory_actions),
        len(execution_actions),
        1 if pending_resolution is not None else 0,
        1 if missing_execution_action else 0,
        metric_payload["memory_applied"],
        metric_payload["execution_applied"],
    )
    return metric_payload


def _apply_pending_resolution(
    *,
    db: Session,
    user,
    decision: Any,
    pending_confirmation,
) -> ConversationTurnOutcome | None:
    resolution = getattr(decision, "pending_resolution", None)
    if resolution is None or pending_confirmation is None:
        return None

    resolution_type = str(getattr(resolution, "type", "") or "")
    if resolution_type == "accept_pending":
        return _accept_pending_confirmation(
            db=db,
            user=user,
            decision=decision,
            pending_confirmation=pending_confirmation,
        )
    if resolution_type == "reject_pending":
        repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="rejected")
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=str(getattr(decision, "fitmas_message", "") or "Compris. Je garde la semaine comme elle est."),
            response_mode="pending_rejected",
            mutation_applied=False,
        )
    if resolution_type in {"modify_pending", "needs_clarification"}:
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=str(getattr(decision, "fitmas_message", "") or "La proposition reste en attente. Dis-moi le changement concret et je reprends."),
            response_mode=f"pending_{resolution_type}",
            mutation_applied=False,
        )
    return None


def _accept_pending_confirmation(
    *,
    db: Session,
    user,
    decision: Any,
    pending_confirmation,
) -> ConversationTurnOutcome:
    try:
        if str(getattr(pending_confirmation, "mutation_type", "") or "") == "plan_patch":
            patch = deserialize_plan_patch_confirmation(pending_confirmation.decision_json)
            service_result = apply_patch_for_user(
                db,
                user=user,
                patch=patch,
                source="conversation",
                trigger_type="pending_confirmation",
                explained_to_user=True,
                allow_requires_confirmation=True,
            )
            applied = _patch_was_applied(service_result)
            if applied:
                repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="accepted")
                return ConversationTurnOutcome(
                    extraction=Extraction(confidence=0.85),
                    reply_text=_applied_patch_summary(service_result, fallback=patch.coach_message),
                    response_mode="pending_accepted",
                    mutation_applied=True,
                )
            return ConversationTurnOutcome(
                extraction=Extraction(confidence=0.85),
                reply_text=_blocked_plan_patch_reply(service_result),
                response_mode="pending_accept_blocked",
                mutation_applied=False,
            )

        pending_decision = deserialize_mutation_decision(pending_confirmation.decision_json)
        service_result = apply_decisions_for_user(
            db,
            user=user,
            decisions=[pending_decision],
            source="conversation",
            trigger_type="pending_confirmation",
            explained_to_user=True,
        )
        applied = _mutation_was_applied(service_result)
        if applied:
            repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="accepted")
            return ConversationTurnOutcome(
                extraction=Extraction(confidence=0.85),
                reply_text=_applied_event_summary(service_result, pending_decision) or pending_decision.fitmas_message,
                response_mode="pending_accepted",
                decision=pending_decision,
                mutation_applied=True,
            )
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_blocked_mutation_reply(pending_decision, service_result),
            response_mode="pending_accept_blocked",
            decision=pending_decision,
            mutation_applied=False,
        )
    except Exception:
        logger.exception("pending_resolution_accept_failed user=%s pending=%s", getattr(user, "id", None), getattr(pending_confirmation, "id", None))
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.5),
            reply_text="Je ne l'applique pas: la confirmation en attente n'est plus valide.",
            response_mode="pending_accept_error",
            mutation_applied=False,
        )


def _patch_was_applied(service_result: PlanPatchServiceResult | None) -> bool:
    if service_result is None or service_result.mutation_result is None:
        return False
    return _mutation_was_applied(service_result.mutation_result)


def _applied_patch_summary(service_result: PlanPatchServiceResult | None, *, fallback: str) -> str:
    if service_result is None or service_result.mutation_result is None:
        return fallback
    summaries: list[str] = []
    for event in service_result.mutation_result.applied_events:
        summary = str(event.user_visible_summary or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
    return " ".join(summaries) if summaries else fallback


def _applied_plan_patch_reply(service_result: PlanPatchServiceResult | None, *, fallback: str) -> str:
    committed_events: list[str] = []
    if service_result is not None and service_result.mutation_result is not None:
        for event in service_result.mutation_result.applied_events:
            summary = str(event.user_visible_summary or "").strip()
            if summary and summary not in committed_events:
                committed_events.append(summary)
    context = final_reply.FinalReplyContext(
        committed_events=tuple(committed_events),
        allowed_to_claim_mutation=bool(committed_events),
        pipeline="conversation",
        pipeline_capability="can_confirm",
    )
    composed = final_reply.compose_final_reply(context)
    if composed:
        return composed
    return " ".join(committed_events) if committed_events else fallback


def _final_reply_context_for_plan_patch_block(
    service_result: PlanPatchServiceResult | None,
) -> final_reply.FinalReplyContext:
    blocked_events: list[final_reply.BlockedEvent] = []
    if service_result is not None:
        for result in service_result.validation.operation_results:
            if result.status == "valid":
                continue
            warning = result.warning_messages[0] if result.warning_messages else None
            blocked_events.append(
                final_reply.BlockedEvent(
                    command=str(result.operation_type or "plan_patch"),
                    reason=result.block_reason,
                    suggested_fix=result.suggested_fix,
                    warning=warning,
                )
            )
    if not blocked_events:
        blocked_events.append(
            final_reply.BlockedEvent(
                command="plan_patch",
                reason="invalid_plan_patch" if service_result is not None else "composer_context_missing",
            )
        )
    return final_reply.FinalReplyContext(
        blocked_events=tuple(blocked_events),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="can_confirm",
    )


def _blocked_plan_patch_reply(service_result: PlanPatchServiceResult | None) -> str:
    context = _final_reply_context_for_plan_patch_block(service_result)
    composed = final_reply.compose_final_reply(context)
    if composed:
        return composed
    return final_reply.outage_fallback_reply(context)


def _execution_applied_patch_blocked_reply(
    db: Session,
    *,
    user,
    action_result: dict,
    service_result: PlanPatchServiceResult | None,
) -> str:
    context = _final_reply_context_for_execution_applied_patch_block(
        db,
        user=user,
        action_result=action_result,
        service_result=service_result,
    )
    composed = final_reply.compose_final_reply(context)
    if composed:
        return composed
    execution_phrase = context.execution_actions_applied[0] if context.execution_actions_applied else "Execution notee."
    return f"{execution_phrase} {final_reply.outage_fallback_reply(context)}"


def _final_reply_context_for_execution_applied_patch_block(
    db: Session,
    *,
    user,
    action_result: dict,
    service_result: PlanPatchServiceResult | None,
) -> final_reply.FinalReplyContext:
    session_ids = tuple(action_result.get("execution_updated_session_ids") or ())
    session = repo.get_scheduled_session(db, user.id, int(session_ids[0])) if session_ids else None
    if session is not None:
        title = str(session.session_title or "La seance").strip()
        status = str(session.completion_status or "").strip()
        execution_phrase = f"{title} notee comme faite." if status == "done" else f"{title} notee comme non faite."
    else:
        execution_phrase = "Execution notee."
    block_context = _final_reply_context_for_plan_patch_block(service_result)
    return final_reply.FinalReplyContext(
        blocked_events=block_context.blocked_events,
        execution_actions_applied=(execution_phrase,),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="can_confirm",
        extra_facts=(
            "Une mise a jour d'execution a ete appliquee, mais le changement planning associe a ete bloque.",
        ),
    )


def _plan_patch_needs_confirmation(service_result: PlanPatchServiceResult | None) -> bool:
    if service_result is None:
        return False
    return service_result.validation.status in {"warning", "requires_confirmation"}


def _plan_patch_confirmation_summary(service_result: PlanPatchServiceResult | None) -> str:
    if service_result is None:
        return "patch planning a confirmer"
    first = service_result.validation.operation_results[0] if service_result.validation.operation_results else None
    if first is not None:
        if first.warning_messages:
            return first.warning_messages[0]
        if first.block_reason:
            return first.block_reason
    return "ce changement modifie sensiblement la semaine"


def _build_plan_patch_confirmation_prompt(service_result: PlanPatchServiceResult | None) -> str:
    summary = _plan_patch_confirmation_summary(service_result)
    context = final_reply.FinalReplyContext(
        pending_summary=summary,
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="can_confirm",
    )
    composed = final_reply.compose_final_reply(context)
    if composed:
        return composed
    return final_reply.outage_fallback_reply(context)


def _log_plan_patch_blocked(service_result: PlanPatchServiceResult | None, *, user_id: int | None) -> None:
    if service_result is None:
        return
    for result in service_result.validation.operation_results:
        if result.status == "valid":
            continue
        logger.warning(
            "plan_patch_blocked user=%s operation=%s status=%s reason=%s target=%s warnings=%s",
            user_id,
            result.operation_type,
            result.status,
            result.block_reason,
            result.target_session_id,
            list(result.warning_codes),
        )


def _blocked_mutation_reply(decision, service_result=None) -> str:
    """Produce a user-facing explanation when a mutation was blocked.

    Prefers a reason-specific message derived from the pre-hook
    `block_reason` (surfaced via `PlanMutationServiceResult.blocked_events`)
    so the user understands the constraint and the LLM, on the next turn,
    sees a concrete rejection rather than a generic "couldn't apply"."""
    block_reason: str | None = None
    warning_hint: str | None = None
    if service_result is not None:
        blocked = getattr(service_result, "blocked_events", ()) or ()
        decision_target = getattr(decision, "target_session_id", None)
        matching = next(
            (
                event for event in blocked
                if event.command_type == getattr(decision, "mutation_type", "")
                and (decision_target is None or event.target_session_id == decision_target)
            ),
            None,
        )
        if matching is None and blocked:
            matching = blocked[0]
        if matching is not None:
            block_reason = matching.block_reason
            warnings = matching.warnings or ()
            warning_hint = warnings[0] if warnings else None

    context = final_reply.FinalReplyContext(
        original_llm_reply=str(getattr(decision, "fitmas_message", "") or ""),
        blocked_events=(
            final_reply.BlockedEvent(
                command=str(getattr(decision, "mutation_type", "") or "mutation"),
                reason=block_reason,
                warning=warning_hint,
            ),
        ) if block_reason or warning_hint else (
            final_reply.BlockedEvent(
                command=str(getattr(decision, "mutation_type", "") or "mutation"),
                reason="mutation_not_validated",
            ),
        ),
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="can_confirm",
    )
    composed = final_reply.compose_final_reply(context)
    if composed:
        return composed
    return final_reply.outage_fallback_reply(context)


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


def _fact_identity(fact: object) -> str:
    if isinstance(fact, dict):
        return f"{fact.get('category')}:{fact.get('key')}"
    return str(fact)


def _turn_plan_payload(turn_plan) -> dict | None:
    if turn_plan is None:
        return None
    if hasattr(turn_plan, "model_dump"):
        payload = turn_plan.model_dump(mode="json")
    else:
        payload = {
            "primary_intent": getattr(turn_plan, "primary_intent", None),
            "secondary_intents": list(getattr(turn_plan, "secondary_intents", ()) or ()),
        }
    payload["has_plan_mutation"] = bool(getattr(turn_plan, "has_plan_mutation", False))
    return payload


def _should_route_availability_context_to_llm(
    turn_plan,
    *,
    week_scope_reply: str | None,
    no_candidate_reply: str | None,
) -> bool:
    # Chantier 1 (autonomy refactor): any availability grounding must reach
    # decide() so the coach can arbitrate the response itself instead of
    # closing the conversation with a templated "rien a bouger". The
    # turn_plan signal is no longer used as a gate.
    return week_scope_reply is not None or no_candidate_reply is not None


def _should_route_adaptation_context_to_llm(
    turn_plan,
    adaptation,
    *,
    plan_mutation_request: bool = False,
) -> bool:
    # Chantier 1 (autonomy refactor): any deterministic adaptation candidate
    # is passed to decide() as context. The LLM arbitrates whether to apply
    # it, modify it, or override it. Direct application without LLM
    # arbitration is no longer allowed in conversation turns.
    return adaptation is not None


def _adaptation_context_for_prompt(adaptation) -> str | None:
    if adaptation is None:
        return None
    scenario = adaptation.selected_scenario
    mutation = scenario.mutation
    lines = [
        "Adaptation candidate deterministe:",
        f"- raison: {adaptation.event.reason_code.value}",
        f"- confiance: {adaptation.event.confidence}",
        f"- mutation candidate: {mutation.mutation_type}",
        f"- session cible: {mutation.target_session_id}",
        f"- date cible: {mutation.target_date}",
        f"- resume: {scenario.summary}",
        f"- message candidate: {adaptation.user_message}",
        "- utilise cette candidate comme option valide, mais arbitre la reponse finale selon le message utilisateur",
    ]
    return "\n".join(lines)


def _availability_context_for_prompt(*, week_scope_reply: str | None, no_candidate_reply: str | None) -> str | None:
    reply = week_scope_reply or no_candidate_reply
    if not reply:
        return None
    return (
        "Contexte orchestration planning:\n"
        f"- grounding deterministe: {reply}\n"
        "- utilise ce grounding comme verite de contexte, mais formule toi-meme la reponse finale\n"
        "- si aucune mutation sure n'est applicable, garde mutation_type=no_change et explique sobrement"
    )

def _execution_contestation_context_for_prompt(reply: str | None) -> str | None:
    """Chantier 1 (autonomy refactor): the deterministic execution
    contestation resolver previously short-circuited the LLM with a
    templated "Je ne compte pas X comme faite" reply. We now expose its
    finding as prompt context so decide() can keep the same factual
    posture but adapt the wording to the conversation thread."""
    if not reply:
        return None
    return (
        "Contexte execution contestation:\n"
        f"- grounding deterministe: {reply}\n"
        "- l'utilisateur conteste une execution: ne compte pas la seance comme faite\n"
        "- formule toi-meme la reponse finale en gardant cette verite de contexte"
    )


def _append_prompt_section(base: str, section: str | None) -> str:
    if not section:
        return base
    return "\n".join(part for part in (base, section) if part)


def _selected_facts_for_prompt(conversation_context, active_facts: list[dict]) -> list[str]:
    import fitmas.api_messages as api_messages

    selected = list(getattr(conversation_context, "selected_facts", ()) or ())
    for fact in api_messages.select_prompt_facts(active_facts):
        if fact not in selected:
            selected.append(fact)
    return selected[:6]


_DIGEST_INTENTS = frozenset({"plan_lookup", "execution_report", "availability_constraint"})


def _maybe_build_coach_reading_digest_text(
    db,
    *,
    user,
    today,
    recent_reality_window,
    turn_plan,
) -> str | None:
    """Build a coach-reading digest when the turn intent calls for it.

    Gated on the turn planner's primary_intent so we don't spend a second LLM
    call on trivial acks or pure mutations (the mutation prompt already has
    plenty of grounding). Degrades silently on any failure: None -> the
    immediate layer just skips the block."""
    primary_intent = getattr(turn_plan, "primary_intent", None) if turn_plan is not None else None
    if primary_intent not in _DIGEST_INTENTS:
        return None
    try:
        digest = build_coach_reading_digest(
            db,
            user,
            today=today,
            recent_reality=recent_reality_window,
        )
    except Exception:
        logger.warning("decide: failed to build coach reading digest", exc_info=True)
        return None
    try:
        return render_digest_for_prompt(digest)
    except Exception:
        logger.warning("decide: failed to render coach reading digest", exc_info=True)
        return None
