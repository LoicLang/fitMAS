from __future__ import annotations

from typing import Any

from fitmas.legacy.coach_decision_provider import (
    CoachDecisionRequest,
    CoachDecisionResult,
    LegacyCoachDecisionProvider,
)
from fitmas.legacy.coach_decision_artifact import (
    LegacyCoachDecisionArtifact,
    legacy_decision_artifact_payload,
)
from fitmas.decision.fallback_census import record_legacy_provider_fallback


def build_legacy_coach_decision_request(
    *,
    user_text: str,
    user,
    state,
    turn_plan,
    coach_bundle,
    conversation_context,
    timeline_summary: str,
    execution_summary: str,
    temporal_summary: str,
    activity_claim_summary: str,
    signal_summary: str,
    selected_facts: list[dict],
    profile_summary: str,
    coach_reading_digest_text: str | None,
    unresolved_execution_followup_text: str | None,
    unresolved_execution_followup_session_id: int | None,
    unresolved_execution_followup_target_date: str | None,
    tool_context: Any | None,
) -> CoachDecisionRequest:
    coach_context = {
        "coach_name": getattr(user, "coach_name", None),
        "coach_style": getattr(user, "coach_style", None),
        "coach_relationship": getattr(user, "coach_relationship", None),
        "coach_do": getattr(user, "coach_do", None),
        "coach_dont": getattr(user, "coach_dont", None),
        "coach_soul": getattr(user, "coach_soul", None),
        "timezone": getattr(user, "timezone", None),
        "today_session_id": getattr(getattr(state, "today_session", None), "id", None),
        "turn_primary_intent": getattr(turn_plan, "primary_intent", None),
        "turn_secondary_intents": list(getattr(turn_plan, "secondary_intents", ()) or ()),
        "turn_plan": _turn_plan_payload(turn_plan),
        "profile_summary": profile_summary,
        "selected_facts": selected_facts,
        "planning_contract": coach_bundle.planning_contract.as_dict(),
        "availability_state": coach_bundle.availability_state.as_dict(),
        "week_mission": coach_bundle.week_mission.as_dict(),
        "recent_reality": coach_bundle.recent_reality.as_dict(),
        "last_adaptation": coach_bundle.latest_adaptation.as_dict()
        if getattr(coach_bundle, "latest_adaptation", None) is not None
        else None,
        "week_context": {
            "summary": getattr(coach_bundle, "week_summary", ""),
            "planning": getattr(coach_bundle, "planning_context", ""),
            "next_week": getattr(coach_bundle, "next_week", ""),
            "coach_reading": getattr(coach_bundle, "coach_reading", ""),
        },
        "coach_reading_digest_text": coach_reading_digest_text,
        "unresolved_execution_followup": unresolved_execution_followup_text,
        "unresolved_execution_followup_session_id": unresolved_execution_followup_session_id,
        "unresolved_execution_followup_target_date": unresolved_execution_followup_target_date,
        "verify_execution_actions": True,
        "repair_memory_actions": True,
    }
    return CoachDecisionRequest(
        user_text=user_text,
        plan_summary="",
        timeline_summary=timeline_summary,
        execution_summary=execution_summary,
        temporal_summary=temporal_summary,
        activity_claim_summary=activity_claim_summary,
        signal_summary=signal_summary,
        conversation_history=getattr(state, "conversation_history", [])[:-1],
        coach_context=coach_context,
        remembered_facts=getattr(state, "active_facts", []),
        time_context=getattr(conversation_context, "time_context", None),
        tool_context=tool_context,
    )


def run_legacy_coach_decision(
    *,
    provider: LegacyCoachDecisionProvider,
    request: CoachDecisionRequest,
    turn_context: dict[str, object],
) -> LegacyCoachDecisionArtifact:
    result = provider.decide(request)
    record_legacy_provider_fallback(
        turn_context,
        response_type=result.artifact.response_type,
        ok=result.ok,
    )
    turn_context["legacy_decide"] = _result_trace(result)
    if result.decide_none_context is not None:
        turn_context["decide_none"] = result.decide_none_context
    return result.artifact


def decide_none_context(turn_context: dict[str, object]) -> dict[str, object]:
    existing = turn_context.get("decide_none")
    if isinstance(existing, dict):
        return existing
    return {
        "reason": "unknown",
        "prompt_trace": None,
        "events": [],
    }


def _result_trace(result: CoachDecisionResult) -> dict[str, object]:
    payload = legacy_decision_artifact_payload(result.artifact)
    return {
        "source": result.source,
        "ok": result.ok,
        "error_type": result.error_type,
        "artifact_kind": result.artifact.kind,
        "response_type": result.artifact.response_type,
        "decision_present": result.artifact.has_value,
        "has_plan_patch": payload["has_plan_patch"],
        "has_pending_resolution": payload["has_pending_resolution"],
        "memory_action_count": payload["memory_action_count"],
        "execution_action_count": payload["execution_action_count"],
        "decide_none_present": result.decide_none_context is not None,
    }


def _turn_plan_payload(turn_plan) -> dict | None:
    if turn_plan is None:
        return None
    if hasattr(turn_plan, "model_dump"):
        return dict(turn_plan.model_dump(mode="json"))
    payload: dict[str, object] = {}
    for name in (
        "primary_intent",
        "secondary_intents",
        "user_goal",
        "mutation_signal",
        "planning_action",
        "execution_claim",
        "availability_constraint",
        "temporal_references",
        "requires_truth_read",
        "truth_scope",
        "needs_clarification",
        "clarification_question",
        "confidence",
    ):
        if hasattr(turn_plan, name):
            value = getattr(turn_plan, name)
            payload[name] = list(value) if isinstance(value, tuple) else value
    return payload
