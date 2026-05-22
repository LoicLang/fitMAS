from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.coach_state_bundle import build_coach_state_bundle
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
    ConversationTurnState,
)
from fitmas.domain.execution.clarification import render_unresolved_execution_followup
from fitmas.grounding_contract import (
    ReplyGroundingPacket,
    plan_window_facts_from_sessions,
    render_grounding_packet_for_prompt,
    resolve_temporal_intents,
)
from fitmas.decision import pending_resolution
from fitmas.decision import plan_patch_reply
from fitmas.profile_summary import build_profile_summary
from fitmas.signals import collect_signals


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TurnContextArtifacts:
    state: ConversationTurnState
    conversation_context: Any
    coach_bundle: Any
    turn_plan: Any
    plan_mutation_request: bool
    clarification: Any | None
    unresolved_execution_followup_text: str | None
    unresolved_execution_followup_session_id: int | None
    unresolved_execution_followup_target_date: str | None
    adaptation: Any | None
    week_scope_reply: str | None
    no_candidate_reply: str | None
    grounding_packet: ReplyGroundingPacket
    grounding_facts: tuple[str, ...]
    turn_context: dict[str, object]


def build_turn_context_artifacts(
    *,
    db: Session,
    user,
    payload: ConversationTurnInput,
    state: ConversationTurnState,
    dependencies: ConversationPipelineDependencies,
    pending_confirmation,
) -> TurnContextArtifacts:
    from fitmas.app.api import routes_messages as api_messages

    pending_confirmation_context = pending_confirmation_context_for_prompt(pending_confirmation)
    external_turn_context: dict[str, object] = {}
    if payload.client_message_key:
        external_turn_context["client_message_key"] = payload.client_message_key
    if payload.source:
        external_turn_context["source"] = payload.source

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
    plan_mutation_request = bool(getattr(turn_plan, "has_plan_mutation", False)) if turn_plan is not None else False

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
    route_adaptation_context_to_llm = should_route_adaptation_context_to_llm(
        turn_plan,
        adaptation,
        plan_mutation_request=plan_mutation_request,
    )
    week_scope_reply = None
    no_candidate_reply = None
    route_availability_context_to_llm = should_route_availability_context_to_llm(
        turn_plan,
        week_scope_reply=week_scope_reply,
        no_candidate_reply=no_candidate_reply,
    )
    grounding_prompt_context = append_prompt_section(
        (
            availability_context_for_prompt(
                week_scope_reply=week_scope_reply,
                no_candidate_reply=no_candidate_reply,
            )
            if route_availability_context_to_llm
            else None
        )
        or "",
        adaptation_context_for_prompt(adaptation) if route_adaptation_context_to_llm else None,
    )
    grounding_prompt_context = append_prompt_section(
        grounding_prompt_context,
        pending_confirmation_context,
    )
    decision_temporal_summary = append_prompt_section(
        temporal_summary_for_prompt(conversation_context),
        grounding_prompt_context,
    )
    decision_signal_summary = append_prompt_section(
        signal_summary_for_prompt(conversation_context),
        grounding_prompt_context,
    )

    grounding_packet = build_reply_grounding_packet(
        user=user,
        local_date=conversation_context.temporal_resolution.local_date,
        scheduled_sessions=state.scheduled_sessions,
        turn_plan=turn_plan,
    )
    grounding_facts = tuple(render_grounding_packet_for_prompt(grounding_packet))

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
            fact_identity(fact)
            for fact in (list(conversation_context.selected_facts) or [])[:6]
        ],
        "turn_plan": turn_plan_payload(turn_plan),
        "grounding": {
            "lines": list(grounding_facts),
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

    return TurnContextArtifacts(
        state=state,
        conversation_context=conversation_context,
        coach_bundle=coach_bundle,
        turn_plan=turn_plan,
        plan_mutation_request=plan_mutation_request,
        clarification=clarification,
        unresolved_execution_followup_text=unresolved_execution_followup_text,
        unresolved_execution_followup_session_id=unresolved_execution_followup_session_id,
        unresolved_execution_followup_target_date=unresolved_execution_followup_target_date,
        adaptation=adaptation,
        week_scope_reply=week_scope_reply,
        no_candidate_reply=no_candidate_reply,
        grounding_packet=grounding_packet,
        grounding_facts=grounding_facts,
        turn_context=turn_context,
    )


def pending_confirmation_context_for_prompt(pending_confirmation) -> str | None:
    if pending_confirmation is None:
        return None
    reason = plan_patch_reply.safe_user_visible_pending_text(str(pending_confirmation.reason or "").strip())
    summary = plan_patch_reply.safe_user_visible_pending_text(str(pending_confirmation.summary or "").strip())
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


def planning_context_from_artifacts(artifacts: TurnContextArtifacts):
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso=artifacts.conversation_context.temporal_resolution.local_date.isoformat()),
        plan=SimpleNamespace(scheduled_sessions=tuple(artifacts.state.scheduled_sessions)),
        execution=SimpleNamespace(activities=tuple(artifacts.state.activities)),
        memory=SimpleNamespace(active_facts=tuple(artifacts.state.active_facts)),
        weekly_digest=SimpleNamespace(coach_reading=artifacts.coach_bundle.coach_reading),
    )


def fact_identity(fact: object) -> str:
    if isinstance(fact, dict):
        return f"{fact.get('category')}:{fact.get('key')}"
    return str(fact)


def build_reply_grounding_packet(
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


def turn_plan_payload(turn_plan) -> dict | None:
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


def should_route_availability_context_to_llm(
    turn_plan,
    *,
    week_scope_reply: str | None,
    no_candidate_reply: str | None,
) -> bool:
    return week_scope_reply is not None or no_candidate_reply is not None


def should_route_adaptation_context_to_llm(
    turn_plan,
    adaptation,
    *,
    plan_mutation_request: bool = False,
) -> bool:
    return adaptation is not None


def adaptation_context_for_prompt(adaptation) -> str | None:
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


def availability_context_for_prompt(*, week_scope_reply: str | None, no_candidate_reply: str | None) -> str | None:
    reply = week_scope_reply or no_candidate_reply
    if not reply:
        return None
    return (
        "Contexte orchestration planning:\n"
        f"- grounding deterministe: {reply}\n"
        "- utilise ce grounding comme verite de contexte, mais formule toi-meme la reponse finale\n"
        "- si aucune mutation sure n'est applicable, garde mutation_type=no_change et explique sobrement"
    )


def append_prompt_section(base: str, section: str | None) -> str:
    if not section:
        return base
    return "\n".join(part for part in (base, section) if part)


def should_use_terminal_close_path(
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
