from __future__ import annotations

import logging
import os

from fitmas.decision import CoachUnderstanding
from fitmas.llm.understanding_service import LLMUnderstandingService, UnderstandingRequest
from fitmas.legacy.coach_command_adapter import commands_from_understanding
from fitmas.legacy.coach_decision_artifact import (
    LegacyCoachDecisionArtifact,
    legacy_decision_artifact_payload,
)

logger = logging.getLogger(__name__)

_COMMAND_INTENTS = {
    "availability_constraint",
    "execution_report",
    "health_signal",
    "availability_signal",
    "preference_signal",
    "memory_update",
}


def understanding_runtime_shadow_enabled() -> bool:
    return _env_flag_enabled("FITMAS_UNDERSTANDING_RUNTIME_SHADOW", default=False)


def understanding_runtime_planning_cutover_enabled() -> bool:
    return _env_flag_enabled("FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", default=False)


def canonical_non_planning_cutover_enabled() -> bool:
    return _env_flag_enabled("FITMAS_CANONICAL_NON_PLANNING_CUTOVER", default=True)


def canonical_provider_pivot_enabled() -> bool:
    return _env_flag_enabled("FITMAS_CANONICAL_PROVIDER_NON_PLANNING", default=True)


def should_run_canonical_understanding(*, turn_plan, pending_confirmation) -> bool:
    if understanding_runtime_shadow_enabled():
        return True
    if _canonical_planning_provider_enabled() and _turn_plan_can_produce_planning(turn_plan):
        return True
    if not canonical_non_planning_cutover_enabled():
        return False
    if _pending_from_understanding_default_enabled() and _has_active_pending(pending_confirmation):
        return True
    if _commands_from_understanding_default_enabled() and _turn_plan_can_produce_non_planning_commands(turn_plan):
        return True
    return False


def should_use_canonical_understanding_without_legacy(
    *,
    understanding: CoachUnderstanding | None,
    turn_plan,
    pending_confirmation,
) -> bool:
    if not canonical_provider_pivot_enabled():
        return False
    if not canonical_non_planning_cutover_enabled():
        return False
    if understanding is None:
        return False
    if understanding.intent == "plan_change" or understanding.requested_change is not None:
        return False
    if (
        _pending_from_understanding_default_enabled()
        and _has_active_pending(pending_confirmation)
        and understanding.pending_resolution is not None
    ):
        return True
    if not _commands_from_understanding_default_enabled():
        return False
    if not _turn_plan_can_produce_non_planning_commands(turn_plan):
        return False
    return bool(commands_from_understanding(understanding).commands)


def coach_decision_artifact_from_understanding(
    understanding: CoachUnderstanding,
    *,
    turn_plan,
) -> LegacyCoachDecisionArtifact:
    response_type = _response_type_for_canonical_artifact(understanding=understanding, turn_plan=turn_plan)
    return LegacyCoachDecisionArtifact(
        kind="coach_decision",
        response_type=response_type,
        rationale=understanding.user_summary,
        reply_hint=_reply_hint_for_canonical_artifact(understanding),
        payload={
            "intent": understanding.intent,
            "confidence": understanding.confidence,
            "signal_count": len(understanding.extracted_signals),
            "has_pending_resolution": understanding.pending_resolution is not None,
            "has_requested_change": understanding.requested_change is not None,
            "canonical_provider_pivot": True,
        },
        source="coach_understanding",
    )


def trace_canonical_provider_artifact(
    artifact: LegacyCoachDecisionArtifact,
) -> dict[str, object]:
    payload = legacy_decision_artifact_payload(artifact)
    return {
        "source": artifact.source,
        "ok": True,
        "error_type": None,
        "artifact_kind": artifact.kind,
        "response_type": artifact.response_type,
        "decision_present": artifact.has_value,
        "has_plan_patch": payload["has_plan_patch"],
        "has_pending_resolution": payload["has_pending_resolution"],
        "memory_action_count": payload["memory_action_count"],
        "execution_action_count": payload["execution_action_count"],
        "decide_none_present": False,
        "legacy_skipped": True,
    }


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _commands_from_understanding_default_enabled() -> bool:
    return _env_flag_enabled("FITMAS_COMMANDS_FROM_UNDERSTANDING", default=True)


def _pending_from_understanding_default_enabled() -> bool:
    return _env_flag_enabled("FITMAS_PENDING_FROM_UNDERSTANDING", default=True)


def _canonical_planning_provider_enabled() -> bool:
    return _env_flag_enabled("FITMAS_CANONICAL_PLANNING_PROVIDER", default=False)


def _has_active_pending(pending_confirmation) -> bool:
    return pending_confirmation is not None and str(getattr(pending_confirmation, "status", "") or "") == "pending"


def _turn_plan_can_produce_planning(turn_plan) -> bool:
    if turn_plan is None:
        return False
    intents = {
        str(getattr(turn_plan, "primary_intent", "") or ""),
        *(str(item or "") for item in tuple(getattr(turn_plan, "secondary_intents", ()) or ())),
    }
    return "plan_mutation" in intents


def _turn_plan_can_produce_non_planning_commands(turn_plan) -> bool:
    if turn_plan is None:
        return False
    intents = {
        str(getattr(turn_plan, "primary_intent", "") or ""),
        *(str(item or "") for item in tuple(getattr(turn_plan, "secondary_intents", ()) or ())),
    }
    if intents.intersection(_COMMAND_INTENTS):
        return True
    if getattr(turn_plan, "availability_constraint", None) is not None:
        return True
    if getattr(turn_plan, "execution_update", None) is not None:
        return True
    return False


def _response_type_for_canonical_artifact(*, understanding: CoachUnderstanding, turn_plan) -> str:
    intent = str(understanding.intent or "")
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    if intent == "execution_report" or primary_intent == "execution_report":
        return "reply"
    return "no_change"


def _reply_hint_for_canonical_artifact(understanding: CoachUnderstanding) -> str:
    if understanding.user_summary:
        return understanding.user_summary
    if understanding.intent == "execution_report":
        return "Signal d'execution compris."
    if understanding.intent == "pending_response":
        return "Confirmation comprise."
    return "Signal compris."


def run_canonical_understanding_shadow(
    *,
    service: LLMUnderstandingService | None = None,
    user,
    user_text: str,
    turn_plan,
    conversation_context,
    coach_bundle,
    state,
    pending_confirmation,
    turn_context: dict[str, object],
) -> CoachUnderstanding | None:
    if not should_run_canonical_understanding(turn_plan=turn_plan, pending_confirmation=pending_confirmation):
        return None
    service = service or LLMUnderstandingService()
    request = UnderstandingRequest(
        event_summary=_event_summary(
            user=user,
            user_text=user_text,
            turn_plan=turn_plan,
            pending_confirmation=pending_confirmation,
        ),
        context_blocks=_context_blocks(
            conversation_context=conversation_context,
            coach_bundle=coach_bundle,
            state=state,
        ),
    )
    try:
        understanding = service.understand(request)
    except Exception:
        logger.exception("decision_runtime.canonical_understanding_failed user=%s", getattr(user, "id", None))
        turn_context["canonical_understanding_error"] = "exception"
        return None
    if understanding is None:
        turn_context["canonical_understanding_error"] = "empty_or_invalid"
        return None
    turn_context["canonical_understanding"] = understanding_to_turn_context_payload(understanding)
    logger.info(
        "decision_runtime.canonical_understanding user=%s intent=%s confidence=%.2f signals=%s requested_change=%s pending=%s",
        getattr(user, "id", None),
        understanding.intent,
        understanding.confidence,
        len(understanding.extracted_signals),
        1 if understanding.requested_change is not None else 0,
        1 if understanding.pending_resolution is not None else 0,
    )
    return understanding


def understanding_to_turn_context_payload(understanding: CoachUnderstanding) -> dict[str, object]:
    requested_change = understanding.requested_change
    pending_resolution = understanding.pending_resolution
    clarification_need = understanding.clarification_need
    return {
        "intent": understanding.intent,
        "confidence": understanding.confidence,
        "user_summary": understanding.user_summary,
        "signals": [
            {
                "type": signal.type,
                "label": signal.label,
                "status": signal.status,
                "severity": signal.severity,
                "confidence": signal.confidence,
                "evidence": signal.evidence,
                "payload": dict(signal.payload),
            }
            for signal in understanding.extracted_signals
        ],
        "requested_change": None
        if requested_change is None
        else {
            "kind": requested_change.kind,
            "source_ref": requested_change.source_ref,
            "target_ref": requested_change.target_ref,
            "desired_sport": requested_change.desired_sport,
            "desired_duration_min": requested_change.desired_duration_min,
            "desired_intensity": requested_change.desired_intensity,
            "reason": requested_change.reason,
            "risk_signals": list(requested_change.risk_signals),
        },
        "pending_resolution": None
        if pending_resolution is None
        else {
            "type": pending_resolution.type,
            "reason": pending_resolution.reason,
            "selected_candidate_id": pending_resolution.selected_candidate_id,
            "requested_changes": pending_resolution.requested_changes,
            "question": pending_resolution.question,
        },
        "clarification_need": None
        if clarification_need is None
        else {
            "reason": clarification_need.reason,
            "missing_fields": list(clarification_need.missing_fields),
            "question_intent": clarification_need.question_intent,
        },
    }


def _event_summary(*, user, user_text: str, turn_plan, pending_confirmation) -> str:
    return (
        f"source=telegram type=user_message user_id={getattr(user, 'id', None)} "
        f"primary_intent={getattr(turn_plan, 'primary_intent', None)} "
        f"pending_active={pending_confirmation is not None} "
        f"text={user_text}"
    )


def _context_blocks(*, conversation_context, coach_bundle, state) -> tuple[str, ...]:
    local_date = getattr(getattr(conversation_context, "temporal_resolution", None), "local_date", None)
    return (
        f"Local date: {local_date}",
        f"Week summary: {getattr(coach_bundle, 'week_summary', '')}",
        f"Planning context: {getattr(coach_bundle, 'planning_context', '')}",
        f"Scheduled sessions count: {len(tuple(getattr(state, 'scheduled_sessions', ()) or ()))}",
        f"Activities count: {len(tuple(getattr(state, 'activities', ()) or ()))}",
        f"Active facts count: {len(tuple(getattr(state, 'active_facts', ()) or ()))}",
    )
