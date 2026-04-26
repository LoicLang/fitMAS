from __future__ import annotations

import logging
from typing import Any

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
from fitmas.claim_guard import looks_like_action_claim, safe_rewrite_for_claim_without_mutation
from fitmas.calibration_needs import (
    build_resolution_memory_updates,
    find_open_calibration_need,
    is_standalone_calibration_answer,
    should_apply_calibration_resolution,
)
from fitmas.coach_reading_digest import build_coach_reading_digest, render_digest_for_prompt
from fitmas.coach_state_bundle import build_coach_state_bundle
from fitmas.execution_clarification import render_unresolved_execution_followup
from fitmas.llm import MutationDecision
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
    MutationImpactAssessment,
    assess_mutation_impact,
    build_confirmation_followup,
    build_confirmation_prompt,
    build_rejection_reply,
    default_confirmation_expiry,
    deserialize_plan_patch_confirmation,
    deserialize_mutation_decision,
    parse_confirmation_reply,
    serialize_plan_patch_confirmation,
    serialize_mutation_decision,
)
from fitmas.plan_mutation_service import PlanPatchServiceResult, apply_decisions_for_user, apply_patch_for_user
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
            decision = (
                None
                if pending_confirmation.mutation_type == "plan_patch"
                else deserialize_mutation_decision(pending_confirmation.decision_json)
            )
            return _reply_and_record_turn(
                db=db,
                user_id=user.id,
                user_text=payload.text,
                reply_text=reply_text,
                extraction=Extraction(confidence=0.98),
                response_mode="confirmation_rejected",
                decision=decision,
                turn_context={
                    "pending_confirmation": True,
                    "pending_confirmation_id": pending_confirmation.id,
                    "pending_confirmation_type": pending_confirmation.mutation_type,
                },
                memory_writes=turn_memory_writes,
            )
        else:
            repo.resolve_pending_mutation_confirmation(db, pending_confirmation.id, status="accepted")
            if pending_confirmation.mutation_type == "plan_patch":
                patch = deserialize_plan_patch_confirmation(pending_confirmation.decision_json)
                service_result = apply_patch_for_user(
                    db,
                    user=user,
                    patch=patch,
                    source="conversation",
                    trigger_type="confirmation_accepted",
                    explained_to_user=True,
                    allow_requires_confirmation=True,
                )
                applied = _patch_was_applied(service_result)
                reply_text = (
                    _applied_patch_summary(service_result, fallback=patch.coach_message)
                    if applied
                    else _blocked_plan_patch_reply(service_result)
                )
                if not applied:
                    _log_plan_patch_blocked(service_result, user_id=user.id)
                return _reply_and_record_turn(
                    db=db,
                    user_id=user.id,
                    user_text=payload.text,
                    reply_text=reply_text,
                    extraction=Extraction(confidence=0.98),
                    response_mode="confirmation_applied" if applied else "confirmation_blocked",
                    mutation_applied=applied,
                    turn_context={
                        "pending_confirmation": True,
                        "pending_confirmation_id": pending_confirmation.id,
                        "pending_confirmation_type": "plan_patch",
                    },
                    memory_writes=turn_memory_writes,
                )
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
                else _blocked_mutation_reply(decision, service_result)
            )
            if not applied:
                _log_mutation_blocked(service_result, user_id=user.id)
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
    low_signal_label = api_messages._maybe_low_signal_label(
        payload.text,
        has_open_calibration_need=open_calibration_need is not None,
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
            # Defense-in-depth: if the message also carries a rich signal
            # (mutation, health, non-completion, availability), do NOT
            # produce the standalone calibration ack here. The calibration
            # fact is persisted above; control continues down to the LLM
            # decide() so it can arbitrate the compound intent.
            if (
                is_standalone_calibration_answer(payload.text)
                and not api_messages._has_rich_signal_marker(payload.text)
            ):
                reply_text = generate_calibration_ack(
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
                return _reply_and_record_turn(
                    db=db,
                    user_id=user.id,
                    user_text=payload.text,
                    reply_text=reply_text,
                    extraction=Extraction(confidence=max(float(calibration_resolution.confidence or 0.0), 0.85)),
                    response_mode="calibration",
                    turn_context={"calibration_need": open_calibration_need.id},
                    memory_writes=turn_memory_writes,
                )

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
    heuristic_plan_mutation_request = api_messages._looks_like_plan_mutation_request(payload.text)

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

    if conversation_context.current_activity_claim is None and resolved_activity_claim is not None:
        claim_summary = "\n".join(
            part for part in (claim_summary, format_activity_claim_for_prompt(resolved_activity_claim)) if part
        )
    if conversation_context.non_completion_claim is None and resolved_non_completion_claim is not None:
        claim_summary = "\n".join(
            part for part in (claim_summary, format_non_completion_claim_for_prompt(resolved_non_completion_claim)) if part
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
        llm_plan_mutation_state = "unavailable"
    else:
        llm_plan_mutation_request = bool(getattr(turn_plan, "has_plan_mutation", False))
        llm_plan_mutation_state = "True" if llm_plan_mutation_request else "False"
    plan_mutation_request = bool(heuristic_plan_mutation_request or llm_plan_mutation_request)
    # Observability (Faille A): the deterministic heuristic and the LLM turn
    # planner are both allowed to signal a plan mutation, and we OR them so
    # neither can silently drop the intent. But a persistent divergence is a
    # drift signal — the heuristic might be missing a new phrasing pattern,
    # or the LLM prompt might be failing to classify obvious mutation verbs.
    # We also distinguish `llm=unavailable` (classifier crashed / timed out)
    # from `llm=False` (classifier returned a clean no): the former is a
    # platform incident, the latter is a classifier disagreement.
    # Emit a structured WARNING on disagreement so we can audit patterns
    # offline without changing runtime behavior.
    if heuristic_plan_mutation_request != llm_plan_mutation_request:
        logger.warning(
            "pipeline.intent_divergence user=%s heuristic=%s llm=%s text=%r",
            getattr(user, "id", None),
            heuristic_plan_mutation_request,
            llm_plan_mutation_state,
            (payload.text or "")[:160],
        )
    if not plan_mutation_request:
        api_messages._apply_non_completion_resolution(
            db=db,
            user=user,
            scheduled_sessions=state.scheduled_sessions,
            timezone_name=user.timezone,
            non_completion_claim=resolved_non_completion_claim,
        )
    if resolved_non_completion_claim is not None and not plan_mutation_request:
        state.scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=21)
        state.timeline = [repo.to_pydantic_scheduled_session(session) for session in state.scheduled_sessions]
        state.today_session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)

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
            user_indication=user_indication,
            resolved_non_completion_claim=resolved_non_completion_claim,
            resolved_activity_claim=resolved_activity_claim,
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

    # Chantier 4 (mémoire contraintes temporelles) : une contrainte multi-jours
    # ("piscine fermée 2 semaines") est persistée comme fact avec expires_at
    # ancré sur la fin de fenêtre. Fait AVANT le traitement health pour que
    # le refresh `_active_memory_payloads` ci-dessous l'inclue si les deux
    # co-occurrent sur un même tour.
    availability_indication_facts = api_messages.build_availability_fact_payloads_from_indication(
        user_indication
    )
    if availability_indication_facts:
        _persist_turn_memory_updates(
            db,
            user.id,
            availability_indication_facts,
            turn_memory_writes=turn_memory_writes,
        )
        state.active_memory_rows, state.active_facts = api_messages._active_memory_payloads(db, user.id)

    health_indication_facts = api_messages.build_health_fact_payloads_from_indication(user_indication)
    health_indication_handled = bool(health_indication_facts)
    defer_health_adaptation_to_llm = bool(health_indication_facts and plan_mutation_request)
    if health_indication_facts:
        _persist_turn_memory_updates(
            db,
            user.id,
            health_indication_facts,
            turn_memory_writes=turn_memory_writes,
        )
        state.active_memory_rows, state.active_facts = api_messages._active_memory_payloads(db, user.id)

    health_adaptation_result = None
    health_fallback_decision = None
    if health_indication_facts and not defer_health_adaptation_to_llm:
        health_adaptation_result = dependencies.check_and_adapt_health_facts(
            db,
            user,
            health_indication_facts,
        )
        if health_adaptation_result and health_adaptation_result.decisions and health_adaptation_result.message:
            health_fallback_decision = health_adaptation_result.decisions[0]

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
    route_adaptation_context_to_llm = _should_route_adaptation_context_to_llm(
        turn_plan,
        adaptation,
        plan_mutation_request=plan_mutation_request,
    )

    standalone_calibration_answer = (
        open_calibration_need is not None
        and should_apply_calibration_resolution(calibration_resolution)
        and adaptation is None
        and is_standalone_calibration_answer(payload.text)
        # When the same message also asks for a mutation, the LLM must
        # arbitrate. The calibration fact is already persisted upstream.
        and not plan_mutation_request
        and not api_messages._has_rich_signal_marker(payload.text)
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
    route_availability_context_to_llm = _should_route_availability_context_to_llm(
        turn_plan,
        week_scope_reply=week_scope_reply,
        no_candidate_reply=no_candidate_reply,
    )
    execution_contestation_reply = (
        None
        if plan_mutation_request
        else api_messages._execution_contestation_reply(
            db=db,
            user=user,
            scheduled_sessions=state.scheduled_sessions,
            activities=state.activities,
            timezone_name=user.timezone,
            non_completion_claim=resolved_non_completion_claim,
        )
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
        _execution_contestation_context_for_prompt(execution_contestation_reply),
    )
    grounding_prompt_context = _append_prompt_section(
        grounding_prompt_context,
        _low_signal_context_for_prompt(low_signal_label),
    )
    decision_temporal_summary = _append_prompt_section(
        temporal_summary_for_prompt(conversation_context),
        grounding_prompt_context,
    )
    decision_signal_summary = _append_prompt_section(
        signal_summary_for_prompt(conversation_context),
        grounding_prompt_context,
    )

    calibration_only_reply = None
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
        "temporal_summary": decision_temporal_summary,
        "activity_claim_summary": claim_summary,
        "signal_summary": decision_signal_summary,
        "history_messages": max(len(state.conversation_history) - 1, 0),
        "selected_fact_keys": [
            _fact_identity(fact)
            for fact in (list(conversation_context.selected_facts) or [])[:6]
        ],
        "user_indication_kind": user_indication.kind.value if user_indication is not None else None,
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
    decision = (
        dependencies.decide(
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
                scheduled_sessions=state.scheduled_sessions,
                activities=state.activities,
                active_facts=state.active_facts,
            ),
        )
        if calibration_only_reply is None
        else None
    )
    # Adaptation fallback: the LLM may legitimately return None when the
    # Anthropic client is unavailable (offline / rate-limited). When a
    # deterministic adaptation candidate exists we apply it transparently
    # so the user still gets the safe arbitration.
    if decision is None and adaptation is not None and calibration_only_reply is None:
        decision = api_messages._to_mutation_decision(adaptation.selected_scenario.mutation, fitmas_message=adaptation.user_message)
    health_fallback_active = False
    if decision is None and health_fallback_decision is not None and calibration_only_reply is None:
        decision = health_fallback_decision
        health_fallback_active = True

    outcome: ConversationTurnOutcome | None = None
    if _is_coach_decision(decision):
        turn_context["coach_decision"] = _coach_decision_payload(decision)
        if decision.response_type == "mutation_decision" and decision.mutation_decision is not None:
            decision = decision.mutation_decision
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
                reply_text = _applied_patch_summary(service_result, fallback=decision.plan_patch.coach_message)
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
            reply_text = api_messages._sanitize_no_change_reply(
                user_text=payload.text,
                reply_text=reply_text,
                decision=legacy_no_change,
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
        extraction_confidence = (
            max(float(user_indication.confidence if user_indication else 0.0), 0.85)
            if health_fallback_active
            else adaptation.event.confidence if adaptation else 0.85
        )
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
        if health_fallback_active and not _can_auto_apply_health_suggestion(
            decision=decision,
            impact=impact,
            user_text=payload.text,
            normalize=api_messages._normalize_text,
        ):
            impact = MutationImpactAssessment(
                level="high",
                requires_confirmation=True,
                reason="health_suggestion_requires_confirmation",
                summary=impact.summary,
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
            reply_text = api_messages._sanitize_no_change_reply(
                user_text=payload.text,
                reply_text=decision.fitmas_message,
                decision=decision,
            )
            outcome = ConversationTurnOutcome(
                extraction=Extraction(confidence=extraction_confidence),
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
                trigger_type=(
                    "health_adaptation"
                    if health_fallback_active
                    else "life_change_adaptation" if adaptation is not None else "message"
                ),
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
            reply_text = api_messages._sanitize_no_change_reply(
                user_text=payload.text,
                reply_text=reply_text,
                decision=decision,
            )
            outcome = ConversationTurnOutcome(
                extraction=Extraction(confidence=extraction_confidence),
                reply_text=reply_text,
                day_updated=api_messages._resolve_day_updated(decision) if applied else None,
                response_mode="mutation_applied" if applied else "mutation_blocked",
                decision=decision,
                mutation_applied=applied,
            )
            logger.info("LLM reply (%s): %s", decision.mutation_type, reply_text[:120])
    elif outcome is None and calibration_only_reply is not None:
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=max(float(calibration_resolution.confidence or 0.0), 0.85)),
            reply_text=calibration_only_reply,
            response_mode="calibration",
        )
        logger.info("Calibration reply: %s", outcome.reply_text[:120])
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

    # Chantier 1bis (anti-mensonge "dire = faire"): if the reply asserts a
    # mutation action ("Je libere ce creneau", "Je deplace cette seance") but
    # no plan_mutation_event was emitted on this turn (no apply, no pending
    # confirmation that would already be worded as a proposal), demote the
    # reply to an explicit clarification request and log a faille.
    mutation_actually_committed = bool(
        outcome.mutation_applied or outcome.pending_confirmation
    )
    if not mutation_actually_committed and looks_like_action_claim(outcome.reply_text):
        logger.warning(
            "conversation_pipeline.claim_without_mutation user=%s text=%r reply=%r",
            user.id,
            payload.text[:120],
            outcome.reply_text[:200],
        )
        outcome.reply_text = safe_rewrite_for_claim_without_mutation()
        outcome.response_mode = "claim_without_mutation_blocked"

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


def _blocked_plan_patch_reply(service_result: PlanPatchServiceResult | None) -> str:
    if service_result is None:
        return "Je ne l'ai pas applique: le patch planning est invalide."
    validation = service_result.validation
    first = validation.operation_results[0] if validation.operation_results else None
    if first is not None:
        if first.block_reason and first.block_reason in _BLOCK_REASON_REPLIES:
            return _BLOCK_REASON_REPLIES[first.block_reason]
        if first.warning_messages:
            return f"Je ne l'ai pas applique: {first.warning_messages[0]}"
        if first.block_reason:
            return f"Je ne l'ai pas applique: {first.block_reason}"
    if validation.status == "requires_confirmation":
        return "Je ne l'applique pas encore: ce changement demande une confirmation claire."
    return "Je ne l'ai pas applique: le changement n'a pas ete valide par le planning."


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
    return f"Je peux le faire, mais ca demande confirmation: {summary}. Tu confirmes ? Reponds oui ou non."


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


_BLOCK_REASON_REPLIES: dict[str, str] = {
    "protected_recovery_target": (
        "Je ne l'ai pas applique: le jour cible est une recuperation protegee, "
        "je ne pose pas de seance dessus. Donne-moi un autre jour, ou precise "
        "un swap (deux seances a echanger) et la recuperation migrera proprement."
    ),
    "same_sport_proximity": (
        "Je ne l'ai pas applique: ca mettrait deux seances du meme sport/type "
        "a moins de 48h, ce qui casse la recuperation. Propose-moi un jour "
        "plus eloigne ou un autre sport sur ce creneau."
    ),
    "occupied_training_target": (
        "Je ne l'ai pas applique: le jour cible a deja une vraie seance. "
        "Si tu veux les echanger, dis-le explicitement et je fais un swap."
    ),
}


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

    if block_reason and block_reason in _BLOCK_REASON_REPLIES:
        return _BLOCK_REASON_REPLIES[block_reason]
    if warning_hint:
        return f"Je ne l'ai pas applique: {warning_hint}"
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


_LOW_SIGNAL_LABEL_HINTS = {
    "ack": (
        "Le message utilisateur est un simple accuse de reception (ex. 'ok', 'merci'). "
        "Reponds sobrement, n'invente pas de decision a annoncer, n'affirme pas un etat du plan."
    ),
    "greeting": (
        "Le message utilisateur est une salutation pure (ex. 'salut', 'hello'). "
        "Reponds brievement et naturellement, sans ouvrir un sujet planning."
    ),
    "motivation": (
        "Le message utilisateur est une expression de motivation pure (ex. 'allez', 'go'). "
        "Reconnais l'energie sans affirmer 'rien a changer' ou autre etat du plan: "
        "tu n'as pas arbitre de decision sur ce tour."
    ),
}


def _low_signal_context_for_prompt(label: str | None) -> str | None:
    if label is None:
        return None
    hint = _LOW_SIGNAL_LABEL_HINTS.get(label)
    if hint is None:
        return None
    return f"Contexte tour low-signal:\n- {hint}"


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
