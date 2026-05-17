from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from threading import Lock
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.adaptation_proposal import compile_adaptation_proposal, generate_adaptation_proposal
from fitmas.grounding_contract import (
    ReplyGroundingPacket,
    plan_window_facts_from_sessions,
    render_grounding_packet_for_prompt,
    resolve_temporal_intents,
)
from fitmas.calibration_llm import extract_calibration_resolution
from fitmas import coach_voice
from fitmas import llm_gateway as gw
from fitmas.claim_guard import (
    build_claim_repair_prompt,
    looks_like_action_claim,
    outage_fallback_reply,
)
from fitmas.decision import DecisionOutcome, DecisionReplyComposer
from fitmas.calibration_needs import (
    build_resolution_memory_updates,
    find_open_calibration_need,
    should_apply_calibration_resolution,
)
from fitmas.coach_reading_digest import build_coach_reading_digest, render_digest_for_prompt
from fitmas.coach_state_bundle import build_coach_state_bundle
from fitmas.execution_clarification import render_unresolved_execution_followup
from fitmas.legacy.final_reply_backend import LegacyFinalReplyBackend
from fitmas.legacy.coach_decision_provider import LegacyCoachDecisionProvider
from fitmas.legacy import conversation_canonical_readonly_bridge
from fitmas.legacy import conversation_canonical_planning_bridge
from fitmas.legacy import conversation_coach_decision_reply_bridge
from fitmas.legacy import conversation_command_bridge
from fitmas.legacy import conversation_decide_bridge
from fitmas.legacy import conversation_decision_bridge
from fitmas.legacy import conversation_pending_bridge
from fitmas.legacy import conversation_planning_bridge
from fitmas.legacy import conversation_readonly_reply_bridge
from fitmas.legacy import conversation_reply_adapter as final_reply
from fitmas.legacy import conversation_understanding_bridge
from fitmas.legacy.plan_patch_reply_adapter import plan_patch_service_result_to_outcome
from fitmas.legacy.understanding_shadow import shadow_understanding_from_legacy_decision
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
from fitmas.models import DayId, Extraction, Message, MessageReply, MessageRole
from fitmas.mutation_permissions import (
    default_confirmation_expiry,
    serialize_plan_patch_choice_confirmation,
    serialize_plan_patch_confirmation,
)
from fitmas.plan_mutation_service import PlanPatchServiceResult, apply_patch_for_user
from fitmas.plan_patch import PlanPatch
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision, decide_adaptation_policy
from fitmas.plan_patch_backend_candidates import build_backend_candidate_refs_for_turn
from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate, evaluate_plan_patch_candidate
from fitmas.plan_patch_candidate_generator import CandidateGenerationInput, generate_plan_patch_candidates
from fitmas.plan_patch_candidate_reviewer import PlanPatchCandidateReviewDecision, review_plan_patch_candidates
from fitmas.plan_patch_candidates import ALLOWED_CANDIDATE_OPERATION_TYPES, PlanPatchCandidate
from fitmas.planning_snapshot import build_planning_snapshot
from fitmas.profile_summary import build_profile_summary
from fitmas.signals import collect_signals
from fitmas.time_context import get_local_now
from fitmas.tools.contract import ToolContext

logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger("fitmas.conversation_metrics")

_CLIENT_MESSAGE_KEY_LOCKS_GUARD = Lock()
_CLIENT_MESSAGE_KEY_LOCKS: dict[str, Lock] = {}


@contextmanager
def _client_message_key_lock(user_id: int, client_message_key: str | None):
    key = str(client_message_key or "").strip()
    if not key:
        yield
        return
    lock_key = f"{user_id}:{key}"
    with _CLIENT_MESSAGE_KEY_LOCKS_GUARD:
        lock = _CLIENT_MESSAGE_KEY_LOCKS.get(lock_key)
        if lock is None:
            lock = Lock()
            _CLIENT_MESSAGE_KEY_LOCKS[lock_key] = lock
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def run_conversation_turn(
    payload: ConversationTurnInput,
    *,
    db: Session,
    dependencies: ConversationPipelineDependencies,
) -> MessageReply:
    user = repo.get_user_optional(db)
    if user is None:
        raise ConversationUserNotFoundError("No onboarded user yet")

    with _client_message_key_lock(user.id, payload.client_message_key):
        return _run_conversation_turn_impl(payload, db=db, dependencies=dependencies)


def _run_conversation_turn_impl(
    payload: ConversationTurnInput,
    *,
    db: Session,
    dependencies: ConversationPipelineDependencies,
) -> MessageReply:
    import fitmas.api_messages as api_messages

    user = repo.get_user_optional(db)
    if user is None:
        raise ConversationUserNotFoundError("No onboarded user yet")

    duplicate_reply = _reply_for_duplicate_client_message(db=db, user_id=user.id, payload=payload)
    if duplicate_reply is not None:
        return duplicate_reply

    state = _load_turn_state(db=db, user=user, user_text=payload.text)
    turn_memory_writes: list[dict] = []
    external_turn_context: dict[str, object] = {}
    if payload.client_message_key:
        external_turn_context["client_message_key"] = payload.client_message_key
    if payload.source:
        external_turn_context["source"] = payload.source
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
        conversation_history=state.conversation_history[:-1],
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
    unresolved_execution_followup_session_id: int | None = None
    unresolved_execution_followup_target_date: str | None = None
    if clarification is not None:
        yesterday = conversation_context.temporal_resolution.local_date.fromordinal(
            conversation_context.temporal_resolution.local_date.toordinal() - 1
        )
        unresolved_execution_followup_session_id = clarification.session_id
        unresolved_execution_followup_target_date = yesterday.isoformat()
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

    grounding_packet = _build_reply_grounding_packet(
        user=user,
        local_date=conversation_context.temporal_resolution.local_date,
        scheduled_sessions=state.scheduled_sessions,
        turn_plan=turn_plan,
    )

    turn_context = {
        **external_turn_context,
        "profile_summary": build_profile_summary(state.active_memory_rows),
        "current_user_message_id": state.current_user_message_id,
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
        "grounding": {
            "lines": list(render_grounding_packet_for_prompt(grounding_packet)),
        },
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
        return _reply_and_record_turn(
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
    if conversation_pending_bridge.should_prepare_canonical_pending_understanding(
        pending_confirmation=pending_confirmation,
    ):
        turn_context["canonical_pending_provider"] = {
            "active_pending_id": getattr(pending_confirmation, "id", None),
            "source": "coach_understanding",
            "result": "prepared",
        }
        canonical_understanding = conversation_understanding_bridge.run_canonical_understanding_shadow(
            user=user,
            user_text=payload.text,
            turn_plan=turn_plan,
            conversation_context=conversation_context,
            coach_bundle=coach_bundle,
            state=state,
            pending_confirmation=pending_confirmation,
            turn_context=turn_context,
        )
        pending_outcome = conversation_pending_bridge.apply_pending_resolution(
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
            return _reply_and_record_turn(
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

    if conversation_canonical_planning_bridge.should_prepare_canonical_planning_understanding(
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
    ):
        canonical_understanding = conversation_understanding_bridge.run_canonical_understanding_shadow(
            user=user,
            user_text=payload.text,
            turn_plan=turn_plan,
            conversation_context=conversation_context,
            coach_bundle=coach_bundle,
            state=state,
            pending_confirmation=pending_confirmation,
            turn_context=turn_context,
        )
        if conversation_canonical_planning_bridge.should_use_canonical_planning_without_legacy(
            understanding=canonical_understanding,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
        ):
            canonical_planning_outcome = conversation_canonical_planning_bridge.handle_canonical_planning(
                understanding=canonical_understanding,
                context=_planning_context_from_turn_state(
                    state=state,
                    conversation_context=conversation_context,
                    coach_bundle=coach_bundle,
                ),
                db=db,
                user=user,
                source_text=payload.text,
                coach_state_bundle=coach_bundle,
                reviewer_request_json_fn=gw.request_json,
                grounding_facts=tuple(render_grounding_packet_for_prompt(grounding_packet)),
                decision_reply_composer_fn=_decision_reply_composer,
                turn_context=turn_context,
            )
            if canonical_planning_outcome is not None:
                return _reply_and_record_turn(
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

    adaptation_candidate_outcome = _maybe_handle_plan_adaptation_candidates(
        db=db,
        user=user,
        user_text=payload.text,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
        open_calibration_need=open_calibration_need,
        scheduled_sessions=state.scheduled_sessions,
        coach_bundle=coach_bundle,
        grounding=grounding_packet,
        turn_context=turn_context,
    )
    if adaptation_candidate_outcome is not None:
        if adaptation_candidate_outcome.response_mode == "obsolete_turn_no_write":
            pass
        elif _turn_is_obsolete(db=db, user=user, turn_context=turn_context):
            adaptation_candidate_outcome = _obsolete_turn_outcome(turn_context=turn_context)
        else:
            conversation_command_bridge.apply_turn_plan_memory_commands(
                db=db,
                user=user,
                turn_plan=turn_plan,
                turn_memory_writes=turn_memory_writes,
                turn_context=turn_context,
            )
        return _reply_and_record_turn(
            db=db,
            user_id=user.id,
            user_text=payload.text,
            reply_text=adaptation_candidate_outcome.reply_text,
            extraction=adaptation_candidate_outcome.extraction,
            response_mode=adaptation_candidate_outcome.response_mode,
            mutation_applied=adaptation_candidate_outcome.mutation_applied,
            pending_confirmation=adaptation_candidate_outcome.pending_confirmation,
            pending_confirmation_id=adaptation_candidate_outcome.pending_confirmation_id,
            turn_context=turn_context,
            memory_writes=turn_memory_writes,
        )

    # CoachDecision remains provider compatibility only. The pipeline receives
    # it through a legacy bridge so runtime authority stays outside `decide()`.
    decision_request = conversation_decide_bridge.build_legacy_coach_decision_request(
        user_text=payload.text,
        user=user,
        state=state,
        turn_plan=turn_plan,
        coach_bundle=coach_bundle,
        conversation_context=conversation_context,
        timeline_summary=api_messages.make_timeline_summary(state.timeline),
        execution_summary=execution_summary_for_prompt(conversation_context),
        temporal_summary=decision_temporal_summary,
        activity_claim_summary=claim_summary,
        signal_summary=decision_signal_summary,
        selected_facts=_selected_facts_for_prompt(conversation_context, state.active_facts),
        profile_summary=build_profile_summary(state.active_memory_rows),
        coach_reading_digest_text=_maybe_build_coach_reading_digest_text(
            db,
            user=user,
            today=conversation_context.temporal_resolution.local_date,
            recent_reality_window=coach_bundle.recent_reality,
            turn_plan=turn_plan,
        ),
        unresolved_execution_followup_text=unresolved_execution_followup_text,
        unresolved_execution_followup_session_id=unresolved_execution_followup_session_id,
        unresolved_execution_followup_target_date=unresolved_execution_followup_target_date,
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
    if canonical_understanding is None:
        canonical_understanding = conversation_understanding_bridge.run_canonical_understanding_shadow(
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
    legacy_decision_artifact = None
    if conversation_understanding_bridge.should_use_canonical_understanding_without_legacy(
        understanding=canonical_understanding,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
    ):
        legacy_decision_artifact = conversation_understanding_bridge.coach_decision_artifact_from_understanding(
            canonical_understanding,
            turn_plan=turn_plan,
        )
        turn_context["legacy_decide"] = conversation_understanding_bridge.trace_canonical_provider_artifact(
            legacy_decision_artifact
        )
    else:
        if conversation_canonical_readonly_bridge.should_use_canonical_readonly_without_legacy(
            understanding=canonical_understanding,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
        ):
            outcome = conversation_canonical_readonly_bridge.compose_canonical_readonly_reply(
                composer=DecisionReplyComposer(reply_backend=LegacyFinalReplyBackend()),
                understanding=canonical_understanding,
                user_text=payload.text,
                turn_plan=turn_plan,
                turn_context=turn_context,
                grounding_facts=tuple(render_grounding_packet_for_prompt(grounding_packet)),
            )
        if outcome is None:
            if conversation_canonical_planning_bridge.should_use_canonical_planning_without_legacy(
                understanding=canonical_understanding,
                turn_plan=turn_plan,
                pending_confirmation=pending_confirmation,
            ):
                outcome = conversation_canonical_planning_bridge.handle_canonical_planning(
                    understanding=canonical_understanding,
                    context=_planning_context_from_turn_state(
                        state=state,
                        conversation_context=conversation_context,
                        coach_bundle=coach_bundle,
                    ),
                    db=db,
                    user=user,
                    source_text=payload.text,
                    coach_state_bundle=coach_bundle,
                    reviewer_request_json_fn=gw.request_json,
                    grounding_facts=tuple(render_grounding_packet_for_prompt(grounding_packet)),
                    decision_reply_composer_fn=_decision_reply_composer,
                    turn_context=turn_context,
                )
        if outcome is None:
            legacy_decision_artifact = conversation_decide_bridge.run_legacy_coach_decision(
                provider=LegacyCoachDecisionProvider(decide_fn=dependencies.decide),
                request=decision_request,
                turn_context=turn_context,
            )
            shadow_understanding_from_legacy_decision(
                user_id=user.id,
                decision_artifact=legacy_decision_artifact,
            )
    is_coach_decision = conversation_decision_bridge.is_coach_decision(legacy_decision_artifact)
    if is_coach_decision:
        turn_context["coach_decision"] = conversation_decision_bridge.coach_decision_payload(legacy_decision_artifact)
        if _turn_is_obsolete(db=db, user=user, turn_context=turn_context):
            outcome = _obsolete_turn_outcome(turn_context=turn_context)
            legacy_decision_artifact = None
        else:
            action_result = _apply_coach_decision_actions(
                db=db,
                user=user,
                decision_artifact=legacy_decision_artifact,
                turn_memory_writes=turn_memory_writes,
                unresolved_execution_followup=unresolved_execution_followup_text,
                turn_plan=turn_plan,
                turn_context=turn_context,
            )
            turn_context["coach_decision_action_result"] = action_result

    if outcome is None:
        pending_outcome = conversation_pending_bridge.apply_pending_resolution(
            db=db,
            user=user,
            decision_artifact=legacy_decision_artifact,
            canonical_understanding=canonical_understanding,
            pending_confirmation=pending_confirmation,
            user_text=payload.text,
            turn_plan=turn_plan,
        )
        if pending_outcome is not None:
            outcome = pending_outcome
            legacy_decision_artifact = None

    if outcome is None and is_coach_decision and legacy_decision_artifact is not None:
        outcome = conversation_planning_bridge.maybe_handle_planning_runtime_cutover(
            decision_artifact=legacy_decision_artifact,
            canonical_understanding=canonical_understanding,
            understanding_planning_cutover_enabled=(
                conversation_understanding_bridge.understanding_runtime_planning_cutover_enabled()
            ),
            state=state,
            conversation_context=conversation_context,
            coach_bundle=coach_bundle,
            db=db,
            user=user,
            source_text=payload.text,
            reviewer_request_json_fn=gw.request_json,
            grounding_facts=render_grounding_packet_for_prompt(grounding_packet),
            planning_context_from_turn_state_fn=_planning_context_from_turn_state,
            decision_reply_composer_fn=_decision_reply_composer,
            compose_no_change_reply_for_turn_fn=conversation_readonly_reply_bridge.compose_no_change_reply_for_turn,
            turn_context=turn_context,
            action_result=turn_context.get("coach_decision_action_result") or {},
        )
        if outcome is not None:
            legacy_decision_artifact = None

    if outcome is None and is_coach_decision and legacy_decision_artifact is not None:
        outcome = conversation_coach_decision_reply_bridge.compose_coach_decision_reply(
            db=db,
            user=user,
            user_text=payload.text,
            decision_artifact=legacy_decision_artifact,
            turn_context=turn_context,
            grounding=grounding_packet,
            action_result=turn_context.get("coach_decision_action_result") or {},
            compose_no_change_reply_for_turn_fn=conversation_readonly_reply_bridge.compose_no_change_reply_for_turn,
        )
        legacy_decision_artifact = None

    if outcome is None and legacy_decision_artifact is not None and _turn_is_obsolete(db=db, user=user, turn_context=turn_context):
        outcome = _obsolete_turn_outcome(turn_context=turn_context)
        legacy_decision_artifact = None

    if (
        outcome is None
        and legacy_decision_artifact is not None
        and conversation_decision_bridge.is_legacy_readonly_decision(legacy_decision_artifact)
    ):
        turn_context["legacy_readonly_decision"] = conversation_decision_bridge.legacy_readonly_decision_payload(
            legacy_decision_artifact
        )
        reply_text, composed_mode = conversation_readonly_reply_bridge.compose_no_change_reply_for_turn(
            db=db,
            user=user,
            user_text=payload.text,
            original_reply=conversation_decision_bridge.legacy_decision_reply_text(legacy_decision_artifact),
            turn_context=turn_context,
            grounding=grounding_packet,
            action_result={},
        )
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=reply_text,
            response_mode=composed_mode or "legacy_readonly_no_change",
            decision=legacy_decision_artifact,
            mutation_applied=False,
        )
        legacy_decision_artifact = None

    if (
        outcome is None
        and legacy_decision_artifact is not None
        and (legacy_decision_artifact.has_value or legacy_decision_artifact.kind == "unsupported")
    ):
        outcome = conversation_planning_bridge.legacy_decision_contract_disabled_outcome(
            decision_artifact=legacy_decision_artifact,
            user_text=payload.text,
            grounding_facts=render_grounding_packet_for_prompt(grounding_packet),
            decision_reply_composer_fn=_decision_reply_composer,
        )
        legacy_decision_artifact = None
    elif outcome is None:
        decide_none_context = conversation_decide_bridge.decide_none_context(turn_context)
        turn_context["decide_none"] = decide_none_context
        decide_none_adaptation_outcome = _maybe_handle_plan_adaptation_candidates(
            db=db,
            user=user,
            user_text=payload.text,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
            open_calibration_need=open_calibration_need,
            scheduled_sessions=state.scheduled_sessions,
            coach_bundle=coach_bundle,
            grounding=grounding_packet,
            turn_context=turn_context,
            mode="post_decide_mixed",
            action_result=turn_context.get("coach_decision_action_result") or {},
        )
        if decide_none_adaptation_outcome is not None:
            turn_context["decide_none_fallback"] = "plan_adaptation_candidates"
            outcome = decide_none_adaptation_outcome

    if outcome is None:
        # Chantier 1 (autonomy refactor): the only remaining path here is
        # "decide() returned None and there is no deterministic adaptation
        # to fall back on" — typically the Anthropic client is unavailable.
        # Reply soberly: do not assert any plan state, do not regurgitate
        # rule-based phrases that could lie about the situation.
        logger.warning("conversation_pipeline: decide() returned None with no fallback decision")
        turn_context.setdefault("decide_none", conversation_decide_bridge.decide_none_context(turn_context))
        outcome = ConversationTurnOutcome(
            extraction=Extraction(confidence=0.5),
            reply_text="Je ne peux pas te repondre tout de suite. Reessaie dans un instant.",
            response_mode="llm_unavailable",
        )

    conversation_pending_bridge.keep_pending_for_non_mutating_turn(
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
    extracted_facts = _filter_legacy_extracted_facts(extracted_facts)
    if extracted_facts:
        _persist_turn_memory_updates(
            db,
            user.id,
            extracted_facts,
            turn_memory_writes=turn_memory_writes,
        )

    conversation_pending_bridge.supersede_pending_if_replaced(
        db=db,
        outcome=outcome,
        pending_confirmation=pending_confirmation,
    )

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


def _reply_for_duplicate_client_message(
    *,
    db: Session,
    user_id: int,
    payload: ConversationTurnInput,
) -> MessageReply | None:
    key = str(payload.client_message_key or "").strip()
    if not key:
        return None
    row = repo.get_conversation_turn_by_client_message_key(db, user_id, key)
    if row is None:
        return None
    logger.info("conversation_pipeline.idempotent_replay user=%s key=%s turn=%s", user_id, key, row.id)
    day_updated = _day_id_from_row(row.day_updated)
    return MessageReply(
        user_message=Message(role=MessageRole.USER, text=row.user_message),
        extraction=Extraction(confidence=float(row.extraction_confidence or 0.0)),
        assistant_message=Message(role=MessageRole.AGENT, text=row.assistant_message),
        day_updated=day_updated,
    )


def _day_id_from_row(raw: str | None) -> DayId | None:
    if not raw:
        return None
    try:
        return DayId(str(raw))
    except ValueError:
        return None


def _turn_is_obsolete(*, db: Session, user, turn_context: dict[str, object]) -> bool:
    raw_message_id = turn_context.get("current_user_message_id")
    try:
        message_id = int(raw_message_id) if raw_message_id is not None else None
    except (TypeError, ValueError):
        message_id = None
    if message_id is None:
        return False
    return repo.has_newer_user_message(db, user.id, message_id)


def _obsolete_turn_outcome(*, turn_context: dict[str, object]) -> ConversationTurnOutcome:
    turn_context["obsolete_turn_no_write"] = True
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=(
            "Je vois un message plus recent. "
            "Je ne touche pas au plan sur cet ancien tour."
        ),
        response_mode="obsolete_turn_no_write",
        mutation_applied=False,
    )


def _load_turn_state(*, db: Session, user, user_text: str) -> ConversationTurnState:
    current_message = repo.add_message(db, user.id, "user", user_text)
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
        current_user_message_id=current_message.id,
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
    reason = _safe_user_visible_pending_text(str(pending_confirmation.reason or "").strip())
    summary = _safe_user_visible_pending_text(str(pending_confirmation.summary or "").strip())
    mutation_type = str(pending_confirmation.mutation_type or "").strip()
    choice_instructions: tuple[str, ...] = ()
    if mutation_type == "plan_patch_choice":
        choice_instructions = (
            "- ce pending contient plusieurs options candidates structurees.",
            "- si le user choisit une option, retourne `pending_resolution.type=accept_pending` "
            "avec `selected_candidate_id` egal a l'id exact de l'option choisie.",
            "- si le choix est ambigu, retourne `pending_resolution.type=needs_clarification`.",
        )
    lines = [
        "Confirmation planning en attente (artefact machine, pas une decision deja appliquee):",
        f"- id: {pending_confirmation.id}",
        f"- type: {mutation_type}",
        f"- raison: {reason}",
        f"- resume: {summary}",
        "- lis le nouveau message dans ce contexte et decide toi-meme.",
        "- si le user accepte clairement, retourne `pending_resolution.type=accept_pending`.",
        "- si le user refuse, retourne `pending_resolution.type=reject_pending`.",
        "- si le user modifie la demande, retourne `modify_pending` avec requested_changes; ne forge pas un nouveau patch libre.",
        "- si le user parle d'autre chose, retourne `ignore` et reponds au nouveau message.",
        *choice_instructions,
        f"- payload: {pending_confirmation.decision_json}",
    ]
    return "\n".join(lines) + "\n"


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


def _planning_context_from_turn_state(*, state, conversation_context, coach_bundle):
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso=conversation_context.temporal_resolution.local_date.isoformat()),
        plan=SimpleNamespace(scheduled_sessions=tuple(state.scheduled_sessions)),
        execution=SimpleNamespace(activities=tuple(state.activities)),
        memory=SimpleNamespace(active_facts=tuple(state.active_facts)),
        weekly_digest=SimpleNamespace(coach_reading=coach_bundle.coach_reading),
    )


def _planning_runtime_cutover_enabled() -> bool:
    return conversation_planning_bridge.planning_runtime_cutover_enabled()


def _decision_reply_composer() -> DecisionReplyComposer:
    return DecisionReplyComposer(reply_backend=LegacyFinalReplyBackend())


def _apply_coach_decision_actions(
    *,
    db: Session,
    user,
    decision_artifact: Any,
    turn_memory_writes: list[dict],
    unresolved_execution_followup: str | None = None,
    turn_plan=None,
    turn_context: dict[str, object] | None = None,
) -> dict[str, Any]:
    return conversation_command_bridge.apply_coach_decision_commands(
        db=db,
        user=user,
        decision_artifact=decision_artifact,
        turn_memory_writes=turn_memory_writes,
        unresolved_execution_followup=unresolved_execution_followup,
        turn_plan=turn_plan,
        canonical_understanding=turn_context.get("canonical_understanding") if isinstance(turn_context, dict) else None,
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
    outcome = plan_patch_service_result_to_outcome(service_result, mode="applied")
    reply_result = _decision_reply_composer().compose(outcome, context=None)
    if reply_result.text and _post_event_reply_matches_plan_patch_result(reply_result.text, service_result):
        return reply_result.text
    committed = " ".join(str(result.payload.get("summary") or "") for result in outcome.applied_commands).strip()
    return committed or fallback


def _post_event_reply_matches_plan_patch_result(
    reply: str,
    service_result: PlanPatchServiceResult | None,
) -> bool:
    if service_result is None or service_result.mutation_result is None:
        return True
    for event in service_result.mutation_result.applied_events:
        if not _post_event_reply_matches_applied_event(reply, event):
            return False
    return True


def _post_event_reply_matches_applied_event(reply: str, event: Any) -> bool:
    if str(getattr(event, "command_type", "") or "") != "move_session":
        return True
    before = _snapshot_date_parts(getattr(event, "before_snapshot", None) or {})
    after = _snapshot_date_parts(getattr(event, "after_snapshot", None) or {})
    if before is None or after is None or before[0] == after[0]:
        return True
    before_iso, before_day = before
    return not (
        _reply_claims_move_destination(reply, before_day)
        or _reply_claims_move_destination(reply, before_iso)
    )


def _snapshot_date_parts(snapshot: dict[str, Any]) -> tuple[str, str] | None:
    raw = str(snapshot.get("scheduled_date") or snapshot.get("day") or "").strip()
    if len(raw) < 10:
        return None
    try:
        parsed = date.fromisoformat(raw[:10])
    except ValueError:
        return None
    days = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    return parsed.isoformat(), days[parsed.weekday()]


def _reply_claims_move_destination(reply: str, destination: str) -> bool:
    normalized = coach_voice.normalize_for_voice_guard(reply)
    target = coach_voice.normalize_for_voice_guard(destination)
    movement = r"(passe|deplace|deplacee|deplacees|cale|calee|calees|bouge|reprogramme|avance|repousse)"
    preposition = r"(a|au|aux|vers|pour|le|la)"
    return bool(
        re.search(
            rf"\b{movement}\b[^.?!]{{0,100}}\b{preposition}\s+{re.escape(target)}\b",
            normalized,
        )
    )


def _applied_event_fact(event: Any) -> str:
    target = event.target_session_id if event.target_session_id is not None else "unknown"
    before = _compact_session_snapshot(getattr(event, "before_snapshot", None) or {})
    after = _compact_session_snapshot(getattr(event, "after_snapshot", None) or {})
    if before or after:
        return f"session change: command={event.command_type} target_session_id={target} before={before or 'unknown'} after={after or 'unknown'}"
    return f"commit command={event.command_type} target_session_id={target}"


def _compact_session_snapshot(snapshot: dict[str, Any]) -> str:
    if not snapshot:
        return ""
    title = str(snapshot.get("session_title") or snapshot.get("title") or "").strip()
    scheduled_date = str(snapshot.get("scheduled_date") or snapshot.get("day") or "").strip()
    sport = str(snapshot.get("sport_type") or "").strip()
    duration = snapshot.get("duration_min")
    bits = [bit for bit in (title, _date_with_day_label(scheduled_date), sport) if bit]
    if duration is not None:
        try:
            bits.append(f"{int(duration)} min")
        except (TypeError, ValueError):
            bits.append(f"{duration} min")
    return " | ".join(bits)


def _date_with_day_label(raw: str) -> str:
    value = str(raw or "").strip()
    if len(value) < 10:
        return value
    try:
        from datetime import date

        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return value
    days = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    return f"{parsed.isoformat()} ({days[parsed.weekday()]})"


def _final_reply_context_for_plan_patch_block(
    service_result: PlanPatchServiceResult | None,
) -> final_reply.FinalReplyContext:
    blocked_events: list[final_reply.BlockedEvent] = []
    if service_result is not None:
        if service_result.week_policy_status == "blocked" and service_result.week_review is not None:
            finding = next(
                (item for item in service_result.week_review.findings if item.severity == "blocked"),
                None,
            )
            blocked_events.append(
                final_reply.BlockedEvent(
                    command="plan_patch",
                    reason=finding.code if finding is not None else "week_coherence_blocked",
                    warning=finding.detail if finding is not None else service_result.week_review.summary,
                    suggested_fix=_week_review_suggested_fix(service_result),
                )
            )
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
    outcome = plan_patch_service_result_to_outcome(service_result, mode="blocked")
    reply_result = _decision_reply_composer().compose(outcome, context=None)
    return reply_result.text or outcome.explanation.reason_summary


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
    return (
        service_result.week_policy_status == "requires_confirmation"
        or service_result.validation.status in {"warning", "requires_confirmation"}
    )


def _plan_patch_service_result_requires_clarification(service_result: PlanPatchServiceResult | None) -> bool:
    if service_result is None:
        return False
    clarification_warning_codes = {
        "ambiguous_target_reference",
    }
    for result in service_result.validation.operation_results:
        if clarification_warning_codes.intersection(result.warning_codes):
            return True
    return False


def _build_plan_patch_clarification_prompt(
    service_result: PlanPatchServiceResult | None,
    *,
    grounding: ReplyGroundingPacket | None = None,
) -> str:
    summary = _plan_patch_clarification_summary(service_result)
    context = final_reply.FinalReplyContext(
        original_llm_reply=summary,
        allowed_to_claim_mutation=False,
        pipeline="conversation",
        pipeline_capability="needs_clarification",
        extra_facts=(
            *render_grounding_packet_for_prompt(grounding),
            f"Clarification requise: {summary}",
            "Aucun changement planning n'a ete commit.",
            "Ne cree pas de pending confirmation.",
        ),
    )
    composed = final_reply.compose_final_reply(context)
    if composed:
        return composed
    return "Je dois identifier quelle séance tu veux bouger avant de toucher la semaine."


def _plan_patch_clarification_summary(service_result: PlanPatchServiceResult | None) -> str:
    if service_result is None:
        return "Il manque la cible exacte du changement."
    for result in service_result.validation.operation_results:
        if "ambiguous_target_reference" in result.warning_codes:
            if result.warning_messages:
                return _safe_user_visible_pending_text(result.warning_messages[0])
            return "Plusieurs séances peuvent correspondre à cette demande."
    return "Il manque la cible exacte du changement."


def _plan_patch_confirmation_summary(service_result: PlanPatchServiceResult | None) -> str:
    if service_result is None:
        return "Changement a confirmer avant de bouger la semaine."
    if service_result.week_policy_status == "requires_confirmation" and service_result.week_review is not None:
        summary = str(service_result.week_review.summary or "").strip()
        if summary:
            return _safe_user_visible_pending_text(summary)
    first = service_result.validation.operation_results[0] if service_result.validation.operation_results else None
    if first is not None:
        if first.warning_messages:
            return _safe_user_visible_pending_text(first.warning_messages[0])
        if first.block_reason:
            return _safe_user_visible_pending_text(first.block_reason)
    return "Ce changement modifie sensiblement la semaine."


def _plan_patch_pending_summary(
    service_result: PlanPatchServiceResult | None,
    *,
    patch: PlanPatch | None = None,
) -> str:
    if service_result is not None and service_result.week_policy_status == "requires_confirmation":
        return _plan_patch_confirmation_summary(service_result)
    for candidate in (
        getattr(patch, "confirmation_reason", None),
        getattr(patch, "coach_message", None),
    ):
        value = str(candidate or "").strip()
        if value and not coach_voice.message_has_user_facing_internal_jargon(value):
            return value
    return _plan_patch_confirmation_summary(service_result)


def _plan_patch_pending_reason(
    service_result: PlanPatchServiceResult | None,
    *,
    fallback_reason: str | None,
) -> str:
    fallback = str(fallback_reason or "").strip()
    if fallback and not coach_voice.message_has_user_facing_internal_jargon(fallback):
        return fallback
    return _plan_patch_confirmation_summary(service_result)


def _safe_user_visible_pending_text(text: str | None) -> str:
    value = str(text or "").strip()
    if not value or coach_voice.message_has_user_facing_internal_jargon(value):
        return "Changement a confirmer avant de bouger la semaine."
    return value


def _plan_patch_confirmation_reply_requests_clarification(reply_text: str | None) -> bool:
    if not reply_text:
        return False
    normalized = coach_voice.normalize_for_voice_guard(str(reply_text))
    clarification_markers = (
        "tu parlais de",
        "tu peux me preciser",
        "tu peux me dire si",
        "preciser laquelle",
        "preciser lesquelles",
        "tu pensais a quel",
        "tu veux dire quel",
        "tu visais",
        "si tu visais",
        "plusieurs seances",
        "quel sport",
        "quelle seance",
        "quel jour",
        "quel creneau",
        "laquelle tu visais",
        "lequel tu visais",
        "laquelle tu veux",
        "lequel tu veux",
        "dit laquelle",
        "dis moi laquelle",
    )
    if any(marker in normalized for marker in clarification_markers):
        return True
    if "?" not in str(reply_text):
        return False
    return bool(re.search(r"\b(quel|quelle|quels|quelles|lequel|laquelle|lesquelles)\b", normalized))


def _week_review_suggested_fix(service_result: PlanPatchServiceResult) -> str | None:
    review = service_result.week_review
    if review is None:
        return None
    for adjustment in review.suggested_adjustments:
        reason = str(adjustment.get("reason") or "").strip()
        if reason:
            return reason
    return None


def _build_plan_patch_confirmation_prompt(
    service_result: PlanPatchServiceResult | None,
    *,
    grounding: ReplyGroundingPacket | None = None,
) -> str:
    outcome = plan_patch_service_result_to_outcome(service_result, mode="pending")
    reply_result = _decision_reply_composer().compose(
        outcome,
        context=None,
        grounding_facts=render_grounding_packet_for_prompt(grounding),
    )
    reply_text = reply_result.text
    fallback = f"{outcome.explanation.reason_summary} Tu confirmes ?"
    if not reply_text:
        return fallback
    if _plan_patch_confirmation_reply_requests_clarification(reply_text):
        return reply_text
    if grounding is None:
        return reply_text

    verified_factual = final_reply.verify_factual_reply(
        reply_text,
        grounding=_plan_patch_confirmation_grounding(
            grounding=grounding,
            service_result=service_result,
        ),
        pipeline_capability="plan_patch_confirmation",
    )
    if not verified_factual:
        return fallback
    rechecked = final_reply.verify_uncommitted_reply(
        verified_factual,
        final_reply.FinalReplyContext(
            pending_summary=outcome.explanation.reason_summary,
            allowed_to_claim_mutation=False,
            pipeline="conversation",
            pipeline_capability="plan_patch_confirmation",
            extra_facts=_plan_patch_confirmation_facts(service_result, grounding=grounding),
        ),
    )
    return rechecked or fallback


def _plan_patch_confirmation_facts(
    service_result: PlanPatchServiceResult | None,
    *,
    grounding: ReplyGroundingPacket | None = None,
) -> tuple[str, ...]:
    patch = service_result.patch if service_result is not None else None
    if patch is None:
        return render_grounding_packet_for_prompt(grounding)
    facts: list[str] = []
    facts.extend(render_grounding_packet_for_prompt(grounding))
    coach_message = str(patch.coach_message or "").strip()
    if coach_message:
        facts.append(f"Patch coach_message: {coach_message}")
    for index, operation in enumerate(patch.operations, start=1):
        bits = [f"operation#{index}", str(operation.operation_type)]
        if operation.target_session_id is not None:
            bits.append(f"target_session_id={operation.target_session_id}")
        if operation.second_session_id is not None:
            bits.append(f"second_session_id={operation.second_session_id}")
        if operation.target_date:
            bits.append(f"target_date={operation.target_date}")
        if operation.new_sport_type:
            bits.append(f"new_sport_type={operation.new_sport_type}")
        if operation.new_session_type:
            bits.append(f"new_session_type={operation.new_session_type}")
        if operation.new_title:
            bits.append(f"new_title={operation.new_title}")
        if operation.new_duration_min is not None:
            bits.append(f"new_duration_min={operation.new_duration_min}")
        if operation.new_intensity:
            bits.append(f"new_intensity={operation.new_intensity}")
        if operation.rationale:
            bits.append(f"rationale={operation.rationale}")
        facts.append(" | ".join(bits))
    return tuple(facts)


def _plan_patch_confirmation_grounding(
    *,
    grounding: ReplyGroundingPacket,
    service_result: PlanPatchServiceResult | None,
) -> ReplyGroundingPacket:
    patch_facts = _plan_patch_confirmation_facts(service_result, grounding=None)
    if not patch_facts:
        return grounding
    return ReplyGroundingPacket(
        local_date=grounding.local_date,
        timezone_name=grounding.timezone_name,
        temporal_references=grounding.temporal_references,
        plan_window=grounding.plan_window,
        extra_facts=tuple(grounding.extra_facts) + patch_facts,
    )


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
        original_llm_reply=conversation_decision_bridge.legacy_decision_reply_text(decision),
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


def _filter_legacy_extracted_facts(payloads: list[dict]) -> list[dict]:
    """Keep the legacy extractor away from availability writes.

    Availability now comes from typed LLM `memory_actions` or the typed
    `turn_plan.availability_constraint`. This function filters only legacy
    extracted fact payloads after the assistant output exists; it never reads
    or classifies user text.
    """
    return [
        payload
        for payload in payloads
        if str(payload.get("category") or "").strip().lower() != "availability"
    ]


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
        decision_json=conversation_decision_bridge.decision_json_for_turn(decision),
        context=turn_context,
        memory_writes=memory_writes,
        client_message_key=str((turn_context or {}).get("client_message_key") or "").strip() or None,
        source=str((turn_context or {}).get("source") or "").strip() or None,
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


def _build_reply_grounding_packet(
    *,
    user,
    local_date,
    scheduled_sessions,
    turn_plan,
) -> ReplyGroundingPacket:
    temporal_refs = resolve_temporal_intents(
        tuple(getattr(turn_plan, "temporal_references", ()) or ()),
        local_date=local_date,
    )
    return ReplyGroundingPacket(
        local_date=local_date,
        timezone_name=getattr(user, "timezone", None),
        temporal_references=temporal_refs,
        plan_window=plan_window_facts_from_sessions(scheduled_sessions),
    )


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


def _adaptation_intent_payload(turn_plan, pending_confirmation) -> dict:
    payload = _turn_plan_payload(turn_plan) or {}
    pending_payload = _pending_confirmation_payload_for_adaptation(pending_confirmation)
    if pending_payload is not None:
        payload["active_pending_confirmation"] = pending_payload
    return payload


def _pending_confirmation_payload_for_adaptation(pending_confirmation) -> dict[str, Any] | None:
    if pending_confirmation is None:
        return None
    if str(getattr(pending_confirmation, "status", "") or "") != "pending":
        return None
    return {
        "id": getattr(pending_confirmation, "id", None),
        "mutation_type": str(getattr(pending_confirmation, "mutation_type", "") or ""),
        "summary": str(getattr(pending_confirmation, "summary", "") or ""),
        "reason": str(getattr(pending_confirmation, "reason", "") or ""),
        "source_text": str(getattr(pending_confirmation, "source_text", "") or ""),
        "decision_json": conversation_pending_bridge.truncate_for_recheck(
            str(getattr(pending_confirmation, "decision_json", "") or ""),
            limit=2500,
        ),
    }


def _should_use_terminal_close_path(
    *,
    turn_plan,
    pending_confirmation,
    open_calibration_need,
) -> bool:
    if turn_plan is None:
        return False
    if str(getattr(turn_plan, "primary_intent", "") or "") != "close_turn":
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


def _maybe_handle_plan_adaptation_candidates(
    *,
    db: Session,
    user,
    user_text: str,
    turn_plan,
    pending_confirmation,
    open_calibration_need,
    scheduled_sessions: list[Any],
    coach_bundle,
    grounding: ReplyGroundingPacket | None,
    turn_context: dict[str, object],
    mode: str = "pre_decide_pure",
    action_result: dict | None = None,
) -> ConversationTurnOutcome | None:
    if not _should_use_plan_adaptation_candidate_flow(
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
        open_calibration_need=open_calibration_need,
        scheduled_sessions=scheduled_sessions,
        mode=mode,
    ):
        return None
    pending_gate = _active_pending_adaptation_gate(
        user_text=user_text,
        pending_confirmation=pending_confirmation,
        turn_context=turn_context,
    )
    if pending_gate is not None:
        if not conversation_pending_bridge.pending_pre_adaptation_allows(pending_gate):
            return None

    current_plan_id, current_plan_version = _current_plan_identity()
    backend_candidate_payloads, backend_candidate_patches = build_backend_candidate_refs_for_turn(
        grounding=grounding,
        scheduled_sessions=scheduled_sessions,
        turn_plan=turn_plan,
    )
    empty_temporal_target = _empty_temporal_plan_mutation_target(
        turn_plan=turn_plan,
        grounding=grounding,
        backend_candidate_payloads=backend_candidate_payloads,
    )
    if empty_temporal_target is not None:
        turn_context["adaptation_candidate_flow"] = {
            "attempted": True,
            "candidates_generated": 0,
            "policy_action": "plan_mutation_empty_target_date",
            "target_dates": [item.isoformat() for item in empty_temporal_target],
        }
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=float(getattr(turn_plan, "confidence", 0.85) or 0.85)),
            reply_text=_empty_temporal_plan_mutation_target_reply(
                dates=empty_temporal_target,
                grounding=grounding,
            ),
            response_mode="plan_mutation_empty_target_date",
            mutation_applied=False,
        )
    no_affected_sport = _availability_no_affected_sport_session(
        turn_plan=turn_plan,
        grounding=grounding,
        scheduled_sessions=scheduled_sessions,
    )
    if no_affected_sport is not None and not backend_candidate_payloads:
        sport_type, starts_on, ends_on = no_affected_sport
        turn_context["adaptation_candidate_flow"] = {
            "attempted": True,
            "candidates_generated": 0,
            "policy_action": "no_change_no_affected_sport_session",
            "constraint_sport_type": sport_type,
            "constraint_start_date": starts_on.isoformat(),
            "constraint_end_date": ends_on.isoformat(),
        }
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=float(getattr(turn_plan, "confidence", 0.85) or 0.85)),
            reply_text=_availability_no_affected_session_reply(
                sport_type=sport_type,
                starts_on=starts_on,
                ends_on=ends_on,
            ),
            response_mode="availability_no_affected_session",
            mutation_applied=False,
        )
    snapshot_outcome = _maybe_handle_plan_adaptation_snapshot_proposal(
        db=db,
        user=user,
        user_text=user_text,
        turn_plan=turn_plan,
        pending_confirmation=pending_confirmation,
        scheduled_sessions=scheduled_sessions,
        coach_bundle=coach_bundle,
        grounding=grounding,
        turn_context=turn_context,
        current_plan_id=current_plan_id,
        current_plan_version=current_plan_version,
        action_result=action_result,
    )
    if snapshot_outcome is not None:
        return snapshot_outcome
    if (
        mode == "pre_decide_pure"
        and pending_confirmation is not None
        and str(getattr(pending_confirmation, "status", "") or "") == "pending"
    ):
        return None

    input_payload = CandidateGenerationInput(
        user_message=user_text,
        parsed_user_intent=_adaptation_intent_payload(turn_plan, pending_confirmation),
        current_plan_summary=_current_plan_summary_for_candidates(scheduled_sessions),
        current_plan_id=current_plan_id,
        current_plan_version=current_plan_version,
        constraints=_candidate_constraints_payload(coach_bundle),
        week_facts=None,
        coherence_findings=(),
        allowed_operations=tuple(sorted(ALLOWED_CANDIDATE_OPERATION_TYPES)),
        forbidden_operations=(),
        pending_context=_pending_confirmation_payload_for_adaptation(pending_confirmation),
        backend_candidates=backend_candidate_payloads,
    )
    candidates = generate_plan_patch_candidates(input_payload, request_json_fn=gw.request_json)
    if not candidates:
        turn_context["adaptation_candidate_flow"] = {
            "attempted": True,
            "candidates_generated": 0,
        }
        return None

    evaluated = tuple(
        evaluate_plan_patch_candidate(
            db,
            candidate=candidate,
            current_plan_id=current_plan_id,
            current_plan_version=current_plan_version,
            plan_id=0,
            scheduled_sessions=scheduled_sessions,
            current_score=None,
            timezone_name=user.timezone,
            coach_state_bundle=coach_bundle,
            backend_candidate_patches=backend_candidate_patches,
        )
        for candidate in candidates
    )
    reviewer_decision = review_plan_patch_candidates(evaluated, request_json_fn=gw.request_json)
    policy_decision = decide_adaptation_policy(evaluated, reviewer_decision=reviewer_decision)
    turn_context["adaptation_candidate_flow"] = _adaptation_candidate_trace(
        candidates=candidates,
        evaluated=evaluated,
        policy_decision=policy_decision,
        reviewer_decision=reviewer_decision,
    )
    return _outcome_from_adaptation_policy(
        db=db,
        user=user,
        user_text=user_text,
        policy_decision=policy_decision,
        evaluated=evaluated,
        coach_bundle=coach_bundle,
        scheduled_sessions=scheduled_sessions,
        grounding=grounding,
        turn_context=turn_context,
        action_result=action_result,
    )


def _active_pending_adaptation_gate(
    *,
    user_text: str,
    pending_confirmation,
    turn_context: dict[str, object],
) -> str | None:
    if pending_confirmation is None:
        return None
    if str(getattr(pending_confirmation, "status", "") or "") != "pending":
        return None
    cached = str(turn_context.get("pending_pre_adaptation_gate") or "").strip()
    if cached:
        return cached
    pending_gate = conversation_pending_bridge.verify_pending_accept_resolution(
        user_text=user_text,
        pending_resolution=None,
        pending_confirmation=pending_confirmation,
    )
    turn_context["pending_pre_adaptation_gate"] = pending_gate
    return pending_gate


def _maybe_handle_plan_adaptation_snapshot_proposal(
    *,
    db: Session,
    user,
    user_text: str,
    turn_plan,
    pending_confirmation,
    scheduled_sessions: list[Any],
    coach_bundle,
    grounding: ReplyGroundingPacket | None,
    turn_context: dict[str, object],
    current_plan_id: str,
    current_plan_version: int,
    action_result: dict | None = None,
) -> ConversationTurnOutcome | None:
    local_date = getattr(grounding, "local_date", None) or get_local_now(user.timezone).date()
    snapshot = build_planning_snapshot(
        db,
        user=user,
        start_date=local_date,
        end_date=local_date + timedelta(days=7),
        now=get_local_now(user.timezone),
    )
    proposal = generate_adaptation_proposal(
        user_message=user_text,
        parsed_user_intent=_adaptation_intent_payload(turn_plan, pending_confirmation),
        snapshot=snapshot,
        request_json_fn=gw.request_json,
        model=gw.DEFAULT_FAST_MODEL,
    )
    if proposal is None:
        turn_context["planning_snapshot_flow"] = {
            "attempted": True,
            "proposal": "none",
            "fallback": "legacy_candidates",
        }
        return None
    if proposal.response_type == "needs_clarification":
        question = str(proposal.clarification_question or "").strip()
        if not question:
            turn_context["planning_snapshot_flow"] = {
                "attempted": True,
                "proposal": "needs_clarification_without_question",
                "fallback": "legacy_candidates",
            }
            return None
        turn_context["planning_snapshot_flow"] = {
            "attempted": True,
            "proposal": "needs_clarification",
            "diagnostics": list(snapshot.diagnostics),
        }
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=float(proposal.confidence or getattr(turn_plan, "confidence", 0.85) or 0.85)),
            reply_text=question,
            response_mode="planning_snapshot_clarification",
            mutation_applied=False,
        )

    compile_result = compile_adaptation_proposal(proposal, snapshot=snapshot)
    if not compile_result.ok or compile_result.patch is None:
        turn_context["planning_snapshot_flow"] = {
            "attempted": True,
            "proposal": "compile_failed",
            "errors": list(compile_result.errors),
            "diagnostics": list(snapshot.diagnostics),
            "fallback": "legacy_candidates",
        }
        return None

    candidate = PlanPatchCandidate(
        id="snapshot_proposal",
        patches=(compile_result.patch,),
        rationale=compile_result.patch.coach_message,
        expected_tradeoff="Adaptation proposee depuis PlanningSnapshot.",
        confidence=float(proposal.confidence or 0.0),
        assumptions=tuple(str(item) for item in proposal.assumptions),
        risk_notes=tuple(snapshot.diagnostics),
        created_from_plan_id=current_plan_id,
        created_from_plan_version=current_plan_version,
    )
    evaluated = (
        evaluate_plan_patch_candidate(
            db,
            candidate=candidate,
            current_plan_id=current_plan_id,
            current_plan_version=current_plan_version,
            plan_id=0,
            scheduled_sessions=scheduled_sessions,
            current_score=None,
            timezone_name=user.timezone,
            coach_state_bundle=coach_bundle,
            backend_candidate_patches={},
        ),
    )
    policy_decision = decide_adaptation_policy(evaluated, reviewer_decision=None)
    turn_context["planning_snapshot_flow"] = {
        "attempted": True,
        "proposal": "compiled",
        "operation_count": len(compile_result.patch.operations),
        "policy_action": policy_decision.action,
        "diagnostics": list(snapshot.diagnostics),
    }
    return _outcome_from_adaptation_policy(
        db=db,
        user=user,
        user_text=user_text,
        policy_decision=policy_decision,
        evaluated=evaluated,
        coach_bundle=coach_bundle,
        scheduled_sessions=scheduled_sessions,
        grounding=grounding,
        turn_context=turn_context,
        action_result=action_result,
    )


def _should_use_plan_adaptation_candidate_flow(
    *,
    turn_plan,
    pending_confirmation,
    open_calibration_need,
    scheduled_sessions: list[Any],
    mode: str = "pre_decide_pure",
) -> bool:
    if turn_plan is None:
        return False
    pending_active = pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending"
    if (
        pending_active
        and mode not in {"post_decide_mixed", "post_decide_plan_mutation"}
        and not _turn_plan_is_primary_plan_mutation(turn_plan)
    ):
        return False
    if open_calibration_need is not None:
        return False
    if not scheduled_sessions:
        return False
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    secondary_intents = {str(item) for item in tuple(getattr(turn_plan, "secondary_intents", ()) or ())}
    if mode == "post_decide_mixed":
        mixed_intents = {"availability_constraint", "execution_report", "health_signal", "plan_mutation"}
        if primary_intent in mixed_intents or secondary_intents.intersection(mixed_intents):
            return bool(getattr(turn_plan, "has_plan_mutation", False))
        return False
    if mode == "post_decide_plan_mutation":
        if primary_intent != "plan_mutation":
            return False
        return bool(getattr(turn_plan, "has_plan_mutation", False))
    if primary_intent != "plan_mutation":
        return False
    if secondary_intents.intersection({"execution_report"}):
        return False
    return bool(getattr(turn_plan, "has_plan_mutation", False))


def _turn_plan_is_primary_plan_mutation(turn_plan) -> bool:
    if turn_plan is None:
        return False
    secondary_intents = {str(item) for item in tuple(getattr(turn_plan, "secondary_intents", ()) or ())}
    if secondary_intents.intersection({"availability_constraint", "execution_report", "health_signal"}):
        return False
    planning_action = str(getattr(turn_plan, "planning_action", "") or "").strip()
    if planning_action in {"", "unknown", "none", "null"}:
        return False
    return (
        str(getattr(turn_plan, "primary_intent", "") or "") == "plan_mutation"
        and bool(getattr(turn_plan, "has_plan_mutation", False))
        and bool(getattr(turn_plan, "mutation_signal", True))
    )


def _availability_no_affected_sport_session(
    *,
    turn_plan,
    grounding: ReplyGroundingPacket | None,
    scheduled_sessions: list[Any],
):
    window = _availability_sport_window_from_turn_plan(turn_plan=turn_plan, grounding=grounding)
    if window is None:
        return None
    sport_type, starts_on, ends_on = window
    for session in scheduled_sessions:
        session_date = _session_date_from_value(getattr(session, "scheduled_date", None))
        if session_date is None or not starts_on <= session_date <= ends_on:
            continue
        status = str(getattr(session, "completion_status", "") or "").strip().lower()
        if status in {"done", "completed"}:
            continue
        if _normalize_turn_sport(getattr(session, "sport_type", None)) == sport_type:
            return None
    return window


def _empty_temporal_plan_mutation_target(
    *,
    turn_plan,
    grounding: ReplyGroundingPacket | None,
    backend_candidate_payloads: tuple[dict[str, Any], ...],
) -> tuple[date, ...] | None:
    if backend_candidate_payloads or turn_plan is None or grounding is None:
        return None
    if str(getattr(turn_plan, "primary_intent", "") or "") != "plan_mutation":
        return None
    if not bool(getattr(turn_plan, "has_plan_mutation", False)):
        return None
    planning_action = str(getattr(turn_plan, "planning_action", "") or "").strip()
    source_dates = _grounding_ref_dates(grounding, "source")
    target_dates = _grounding_ref_dates(grounding, "target")
    context_dates = _grounding_ref_dates(grounding, "context")
    if not source_dates and not target_dates and not context_dates:
        return None
    if source_dates:
        if planning_action not in {"move_session", "swap_sessions", "replace_session", "lighten_day", "update_session"}:
            return None
        missing = source_dates - _training_dates_in_grounding(grounding, source_dates)
        return tuple(sorted(missing)) if missing else None
    if planning_action not in {"swap_sessions", "replace_session", "lighten_day", "update_session"}:
        return None
    candidate_dates = target_dates | context_dates
    if not candidate_dates:
        return None
    if _training_dates_in_grounding(grounding, candidate_dates):
        return None
    return tuple(sorted(candidate_dates))


def _empty_temporal_plan_mutation_target_reply(
    *,
    dates: tuple[date, ...],
    grounding: ReplyGroundingPacket | None,
) -> str:
    labels = ", ".join(_grounding_date_label(item, grounding=grounding) for item in dates)
    return (
        f"Je ne vois aucune seance a modifier le {labels}. "
        "Je ne touche pas au plan. Donne-moi la seance cible, ou dis-moi si tu veux en ajouter une."
    )


def _grounding_ref_dates(grounding: ReplyGroundingPacket, role: str) -> set[date]:
    return {
        ref.resolved_date
        for ref in grounding.temporal_references.get(role, ())
        if isinstance(getattr(ref, "resolved_date", None), date)
    }


def _training_dates_in_grounding(grounding: ReplyGroundingPacket, dates: set[date]) -> set[date]:
    return {
        fact.scheduled_date
        for fact in grounding.plan_window
        if fact.scheduled_date in dates and str(fact.slot_kind or "") == "training"
    }


def _grounding_date_label(value: date, *, grounding: ReplyGroundingPacket | None) -> str:
    if grounding is not None:
        for refs in grounding.temporal_references.values():
            for ref in refs:
                if ref.resolved_date == value:
                    return f"{value.isoformat()} ({ref.day_label})"
    return value.isoformat()


def _availability_sport_window_from_turn_plan(
    *,
    turn_plan,
    grounding: ReplyGroundingPacket | None,
):
    raw = getattr(turn_plan, "availability_constraint", None)
    if not isinstance(raw, dict):
        return None
    availability = str(raw.get("availability") or "").strip().lower()
    if availability not in {"unavailable", "limited"}:
        return None
    sport_type = _normalize_turn_sport(raw.get("sport_type"))
    if sport_type in {None, "general", "all", "rest", "off"}:
        return None
    if raw.get("starts_on") in {None, "", "unknown"} or raw.get("ends_on") in {None, "", "unknown"}:
        return None
    starts_on = _session_date_from_value(raw.get("starts_on")) or getattr(grounding, "local_date", None)
    ends_on = _session_date_from_value(raw.get("ends_on"))
    if starts_on is None or ends_on is None or ends_on < starts_on:
        return None
    return sport_type, starts_on, ends_on


def _availability_no_affected_session_reply(*, sport_type: str, starts_on, ends_on) -> str:
    sport_label = _sport_label_fr(sport_type)
    return (
        f"Je note l'indisponibilite {sport_label} du {starts_on.isoformat()} au {ends_on.isoformat()}. "
        f"Aucune seance {sport_label} n'est prevue dans cette fenetre, donc je ne touche pas au plan."
    )


def _normalize_turn_sport(value: object) -> str | None:
    sport = str(value or "").strip().lower()
    aliases = {
        "swim": "swimming",
        "natation": "swimming",
        "piscine": "swimming",
        "run": "running",
        "course": "running",
        "course_a_pied": "running",
        "velo": "cycling",
        "bike": "cycling",
        "biking": "cycling",
        "renfo": "strength",
        "muscu": "strength",
        "musculation": "strength",
        "escalade": "climbing",
    }
    return aliases.get(sport, sport or None)


def _sport_label_fr(sport_type: str) -> str:
    return {
        "swimming": "natation",
        "running": "running",
        "cycling": "velo",
        "strength": "renfo",
        "climbing": "escalade",
    }.get(sport_type, sport_type)


def _session_date_from_value(value: object):
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "isoformat") and hasattr(value, "weekday"):
        return value
    if isinstance(value, str):
        try:
            from datetime import date

            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _outcome_from_adaptation_policy(
    *,
    db: Session,
    user,
    user_text: str,
    policy_decision: AdaptationPolicyDecision,
    evaluated: tuple[EvaluatedPlanPatchCandidate, ...],
    coach_bundle,
    scheduled_sessions: list[Any],
    grounding: ReplyGroundingPacket | None,
    turn_context: dict[str, object],
    action_result: dict | None = None,
) -> ConversationTurnOutcome | None:
    extra_facts = _adaptation_action_extra_facts(db=db, user=user, action_result=action_result)
    if policy_decision.action == "block":
        reply_text = final_reply.compose_plan_adaptation_reply(
            policy_decision=policy_decision,
            user_text=user_text,
            candidate_summaries=_candidate_summaries_for_reply(evaluated, scheduled_sessions=scheduled_sessions),
            extra_facts=extra_facts,
        ) or final_reply.outage_fallback_reply(
            final_reply.build_plan_adaptation_reply_context(
                policy_decision=policy_decision,
                user_text=user_text,
            )
        )
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=reply_text,
            response_mode="plan_adaptation_block",
            mutation_applied=False,
        )

    if _turn_is_obsolete(db=db, user=user, turn_context=turn_context):
        return _obsolete_turn_outcome(turn_context=turn_context)

    if policy_decision.action == "pending_choice":
        choice_candidates = _pending_choice_candidates(policy_decision, evaluated)
        pending_row = repo.create_pending_mutation_confirmation(
            db,
            user_id=user.id,
            impact_level="medium",
            reason=policy_decision.requires_confirmation_reason or policy_decision.reason,
            mutation_type="plan_patch_choice",
            summary=_pending_choice_summary(choice_candidates),
            source_text=user_text,
            decision_json=serialize_plan_patch_choice_confirmation(
                _pending_choice_serialization_candidates(choice_candidates)
            ),
            expires_at=default_confirmation_expiry(),
        )
        reply_text = final_reply.compose_plan_adaptation_reply(
            policy_decision=policy_decision,
            user_text=user_text,
            candidate_summaries=_candidate_summaries_for_reply(evaluated, scheduled_sessions=scheduled_sessions),
            extra_facts=extra_facts,
        ) or final_reply.outage_fallback_reply(
            final_reply.build_plan_adaptation_reply_context(
                policy_decision=policy_decision,
                user_text=user_text,
            )
        )
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=reply_text,
            response_mode="plan_adaptation_pending_choice",
            mutation_applied=False,
            pending_confirmation=True,
            pending_confirmation_id=pending_row.id,
        )

    selected = _selected_evaluated_candidate(policy_decision, evaluated)
    if selected is None or selected.patch is None or selected.patch_validation is None:
        return None

    if policy_decision.action == "pending_confirmation":
        service_result = PlanPatchServiceResult(validation=selected.patch_validation, patch=selected.patch)
        pending_row = repo.create_pending_mutation_confirmation(
            db,
            user_id=user.id,
            impact_level="high",
            reason=policy_decision.requires_confirmation_reason or policy_decision.reason,
            mutation_type="plan_patch",
            summary=_plan_patch_pending_summary(service_result, patch=selected.patch),
            source_text=user_text,
            decision_json=serialize_plan_patch_confirmation(selected.patch),
            expires_at=default_confirmation_expiry(),
        )
        reply_text = final_reply.compose_plan_adaptation_reply(
            policy_decision=policy_decision,
            user_text=user_text,
            candidate_summaries=_candidate_summaries_for_reply((selected,), scheduled_sessions=scheduled_sessions),
            extra_facts=extra_facts,
        )
        if not _plan_adaptation_reply_hard_guard_allows(
            reply_text,
            scheduled_sessions=scheduled_sessions,
            patch=selected.patch,
            grounding=grounding,
        ):
            reply_text = _plan_patch_pending_fallback_reply(selected.patch)
        reply_text = reply_text or _build_plan_patch_confirmation_prompt(service_result, grounding=grounding)
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=reply_text,
            response_mode="plan_adaptation_pending_confirmation",
            mutation_applied=False,
            pending_confirmation=True,
            pending_confirmation_id=pending_row.id,
        )

    if policy_decision.action != "commit":
        return None

    service_result = apply_patch_for_user(
        db,
        user=user,
        patch=selected.patch,
        source="conversation",
        trigger_type="plan_adaptation_candidate",
        explained_to_user=True,
        coach_state_bundle=coach_bundle,
        activities=(),
        active_facts=(),
    )
    if _patch_was_applied(service_result):
        committed_events = _committed_event_summaries(service_result)
        reply_text = final_reply.compose_plan_adaptation_reply(
            policy_decision=policy_decision,
            user_text=user_text,
            committed_events=committed_events,
            candidate_summaries=_candidate_summaries_for_reply((selected,), scheduled_sessions=scheduled_sessions),
            extra_facts=extra_facts,
        )
        if not _plan_adaptation_reply_hard_guard_allows(
            reply_text,
            scheduled_sessions=scheduled_sessions,
            patch=selected.patch,
            grounding=grounding,
        ):
            reply_text = None
        reply_text = reply_text or _applied_plan_patch_reply(service_result, fallback=selected.patch.coach_message)
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=reply_text,
            response_mode="plan_adaptation_commit",
            mutation_applied=True,
        )
    if _plan_patch_needs_confirmation(service_result):
        pending_row = repo.create_pending_mutation_confirmation(
            db,
            user_id=user.id,
            impact_level="high",
            reason=_plan_patch_pending_reason(
                service_result,
                fallback_reason="plan_adaptation_runtime_confirmation",
            ),
            mutation_type="plan_patch",
            summary=_plan_patch_pending_summary(service_result, patch=selected.patch),
            source_text=user_text,
            decision_json=serialize_plan_patch_confirmation(selected.patch),
            expires_at=default_confirmation_expiry(),
        )
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=_build_plan_patch_confirmation_prompt(service_result, grounding=grounding),
            response_mode="plan_adaptation_runtime_confirmation",
            mutation_applied=False,
            pending_confirmation=True,
            pending_confirmation_id=pending_row.id,
        )
    _log_plan_patch_blocked(service_result, user_id=user.id)
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=_blocked_plan_patch_reply(service_result),
        response_mode="plan_adaptation_runtime_block",
        mutation_applied=False,
    )


def _current_plan_identity() -> tuple[str, int]:
    # Phase A contract identity: the generator echoes these values back, then
    # deterministic validation only checks the structured candidate artifact.
    return "plan_current", 1


def _current_plan_summary_for_candidates(scheduled_sessions: list[Any]) -> dict[str, Any]:
    return {
        "sessions": [
            {
                "id": getattr(session, "id", None),
                "scheduled_date": str(getattr(session, "scheduled_date", "") or ""),
                "day": getattr(session, "day", None),
                "title": getattr(session, "session_title", None),
                "sport_type": getattr(session, "sport_type", None),
                "session_type": getattr(session, "session_type", None),
                "duration_min": getattr(session, "duration_min", None),
                "intensity": getattr(session, "intensity", None),
                "priority": getattr(session, "priority", None),
                "completion_status": getattr(session, "completion_status", None),
            }
            for session in scheduled_sessions[:14]
        ]
    }


def _candidate_constraints_payload(coach_bundle) -> dict[str, Any]:
    return {
        "planning_contract": coach_bundle.planning_contract.as_dict(),
        "availability_state": coach_bundle.availability_state.as_dict(),
        "week_mission": coach_bundle.week_mission.as_dict(),
        "recent_reality": coach_bundle.recent_reality.as_dict(),
    }


def _adaptation_candidate_trace(
    *,
    candidates: tuple[PlanPatchCandidate, ...],
    evaluated: tuple[EvaluatedPlanPatchCandidate, ...],
    policy_decision: AdaptationPolicyDecision,
    reviewer_decision: PlanPatchCandidateReviewDecision | None = None,
) -> dict[str, Any]:
    return {
        "attempted": True,
        "candidates_generated": len(candidates),
        "candidates_evaluated": len(evaluated),
        "candidate_ids": [candidate.id for candidate in candidates],
        "candidate_refs": [candidate.candidate_ref for candidate in candidates if candidate.candidate_ref],
        "policy_action": policy_decision.action,
        "selected_candidate_id": policy_decision.selected_candidate_id,
        "candidate_options": list(policy_decision.candidate_options),
        "risk_level": policy_decision.risk_level,
        "reviewer": (
            {
                "preferred_candidate_id": reviewer_decision.preferred_candidate_id,
                "confidence": reviewer_decision.confidence,
                "rationale": list(reviewer_decision.rationale),
            }
            if reviewer_decision is not None
            else None
        ),
        "evaluations": [
            {
                "candidate_id": item.candidate.id,
                "candidate_validation": item.candidate_validation.status,
                "patch_validation": item.patch_validation.status if item.patch_validation is not None else None,
                "score_total": item.score.total if item.score is not None else None,
                "score_delta": item.score_delta,
                "policy_hint": item.policy_hint,
            }
            for item in evaluated
        ],
    }


def _selected_evaluated_candidate(
    policy_decision: AdaptationPolicyDecision,
    evaluated: tuple[EvaluatedPlanPatchCandidate, ...],
) -> EvaluatedPlanPatchCandidate | None:
    selected_id = policy_decision.selected_candidate_id
    if not selected_id:
        return None
    return next((item for item in evaluated if item.candidate.id == selected_id), None)


def _pending_choice_candidates(
    policy_decision: AdaptationPolicyDecision,
    evaluated: tuple[EvaluatedPlanPatchCandidate, ...],
) -> tuple[EvaluatedPlanPatchCandidate, ...]:
    option_ids = set(policy_decision.candidate_options)
    if not option_ids:
        return evaluated
    return tuple(item for item in evaluated if item.candidate.id in option_ids)


def _pending_choice_serialization_candidates(
    evaluated: tuple[EvaluatedPlanPatchCandidate, ...],
) -> tuple[PlanPatchCandidate, ...]:
    candidates: list[PlanPatchCandidate] = []
    for item in evaluated:
        if item.candidate.patches:
            candidates.append(item.candidate)
            continue
        if item.patch is None:
            continue
        candidates.append(
            PlanPatchCandidate(
                id=item.candidate.id,
                patches=(item.patch,),
                rationale=item.candidate.rationale,
                expected_tradeoff=item.candidate.expected_tradeoff,
                confidence=item.candidate.confidence,
                assumptions=item.candidate.assumptions,
                risk_notes=item.candidate.risk_notes,
                created_from_plan_id=item.candidate.created_from_plan_id,
                created_from_plan_version=item.candidate.created_from_plan_version,
            )
        )
    return tuple(candidates)


def _pending_choice_summary(evaluated: tuple[EvaluatedPlanPatchCandidate, ...]) -> str:
    if not evaluated:
        return "Choix d'adaptation en attente."
    option_bits = [f"{item.candidate.id}: {item.candidate.rationale}" for item in evaluated]
    return "Options d'adaptation en attente: " + " | ".join(option_bits)


def _candidate_summaries_for_reply(
    evaluated: tuple[EvaluatedPlanPatchCandidate, ...],
    *,
    scheduled_sessions: list[Any] | tuple[Any, ...] = (),
) -> tuple[str, ...]:
    session_labels = _session_labels_by_id(scheduled_sessions)
    summaries: list[str] = []
    for item in evaluated:
        score = f"score={item.score.total}" if item.score is not None else "score=unknown"
        operations = _patch_operations_summary(item.patch, session_labels=session_labels)
        ops_text = f" | ops={operations}" if operations else ""
        summaries.append(
            f"{item.candidate.id}: {item.candidate.rationale} | "
            f"tradeoff={item.candidate.expected_tradeoff}{ops_text} | {score}"
        )
    return tuple(summaries)


def _plan_adaptation_reply_hard_guard_allows(
    reply_text: str | None,
    *,
    scheduled_sessions: list[Any] | tuple[Any, ...],
    patch: PlanPatch | None = None,
    grounding: ReplyGroundingPacket | None = None,
) -> bool:
    if not reply_text:
        return False
    text = str(reply_text).lower()
    mentioned_durations = {
        int(raw_value)
        for raw_value in re.findall(r"\b(\d{1,3})\s*(?:min|minute|minutes)\b", text)
    }
    if not mentioned_durations:
        duration_ok = True
    else:
        allowed_durations = {
            int(duration)
            for session in scheduled_sessions
            if (duration := getattr(session, "duration_min", None)) is not None
        }
        duration_ok = not allowed_durations or mentioned_durations.issubset(allowed_durations)
    if not duration_ok:
        return False
    if grounding is None or patch is None:
        return True
    mentioned_relative_dates = _mentioned_relative_dates(text, grounding=grounding)
    if not mentioned_relative_dates:
        return True
    allowed_dates = _patch_related_dates(patch=patch, scheduled_sessions=scheduled_sessions)
    return not allowed_dates or mentioned_relative_dates.issubset(allowed_dates)


def _mentioned_relative_dates(text: str, *, grounding: ReplyGroundingPacket) -> set[date]:
    local_date = getattr(grounding, "local_date", None)
    if local_date is None:
        return set()
    dates: set[date] = set()
    if "aujourd" in text:
        dates.add(local_date)
    if "demain" in text:
        dates.add(local_date + timedelta(days=1))
    if "hier" in text:
        dates.add(local_date - timedelta(days=1))
    return dates


def _patch_related_dates(
    *,
    patch: PlanPatch,
    scheduled_sessions: list[Any] | tuple[Any, ...],
) -> set[date]:
    sessions_by_id = {
        int(getattr(session, "id")): session
        for session in scheduled_sessions
        if getattr(session, "id", None) is not None
    }
    dates: set[date] = set()
    for operation in patch.operations:
        for field_name in ("target_session_id", "second_session_id"):
            session_id = getattr(operation, field_name, None)
            session = sessions_by_id.get(int(session_id)) if session_id is not None else None
            session_date = _session_date_from_value(getattr(session, "scheduled_date", None)) if session is not None else None
            if session_date is not None:
                dates.add(session_date)
        target_date = _session_date_from_value(getattr(operation, "target_date", None))
        if target_date is not None:
            dates.add(target_date)
    return dates


def _plan_patch_pending_fallback_reply(patch: PlanPatch | None) -> str | None:
    if patch is None:
        return None
    summary = str(getattr(patch, "coach_message", "") or "").strip()
    if not summary:
        summary = _patch_operations_summary(patch, session_labels={})
    if not summary:
        return None
    return f"Je te propose: {summary}. Tu confirmes ?"


def _session_labels_by_id(scheduled_sessions: list[Any] | tuple[Any, ...]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for session in scheduled_sessions:
        session_id = getattr(session, "id", None)
        if session_id is None:
            continue
        session_date = _session_date_from_value(getattr(session, "scheduled_date", None))
        date_text = session_date.isoformat() if session_date is not None else "date_unknown"
        sport_type = str(getattr(session, "sport_type", "") or "sport_unknown").strip() or "sport_unknown"
        session_type = str(getattr(session, "session_type", "") or "type_unknown").strip() or "type_unknown"
        labels[int(session_id)] = f"session:{int(session_id)} {sport_type}/{session_type} {date_text}"
    return labels


def _patch_operations_summary(
    patch: PlanPatch | None,
    *,
    session_labels: dict[int, str],
) -> str:
    if patch is None:
        return ""
    parts: list[str] = []
    for operation in patch.operations:
        operation_type = str(getattr(operation, "operation_type", "") or "operation")
        target_id = getattr(operation, "target_session_id", None)
        second_id = getattr(operation, "second_session_id", None)
        target_label = session_labels.get(int(target_id), f"session:{target_id}") if target_id is not None else "session:unknown"
        if operation_type == "swap_sessions" and second_id is not None:
            second_label = session_labels.get(int(second_id), f"session:{second_id}")
            parts.append(f"swap_sessions {target_label} <-> {second_label}")
            continue
        target_date = getattr(operation, "target_date", None)
        if target_date:
            parts.append(f"{operation_type} {target_label} -> {target_date}")
        else:
            parts.append(f"{operation_type} {target_label}")
    return "; ".join(parts)


def _committed_event_summaries(service_result: PlanPatchServiceResult | None) -> tuple[str, ...]:
    if service_result is None or service_result.mutation_result is None:
        return ()
    summaries: list[str] = []
    for event in service_result.mutation_result.applied_events:
        summary = str(event.user_visible_summary or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
    return tuple(summaries)


def _adaptation_action_extra_facts(
    *,
    db: Session,
    user,
    action_result: dict | None,
) -> tuple[str, ...]:
    if not action_result:
        return ()
    return (
        *conversation_readonly_reply_bridge.memory_action_phrases_for_final_reply(action_result),
        *conversation_readonly_reply_bridge.execution_action_phrases_for_final_reply(
            db,
            user=user,
            action_result=action_result,
        ),
    )


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


_DIGEST_INTENTS = frozenset({"execution_report", "availability_constraint"})


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
