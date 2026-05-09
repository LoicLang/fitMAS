from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from time import perf_counter
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from fitmas import coach_voice, llm_gateway as gw
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.fact_memory import normalize_fact_payload as normalize_fact_memory_payload
from fitmas.fact_memory import select_relevant_facts
from fitmas.knowledge import load_sport_knowledge
from fitmas.llm_prompt_builder import build_layered_conversation_prompt, render_conversation_time_block
from fitmas.onboarding_contract import build_coach_profile, build_goal_summary
from fitmas.prompt_observability import DecideFailureReason, PromptTrace
from fitmas.profile_summary import build_profile_summary
from fitmas.time_context import build_time_context, render_time_context
from fitmas.tools.contract import ToolCall, ToolContext
from fitmas.tools.metrics import build_tool_trace, log_tool_trace
from fitmas.tools.registry import list_tools_for_pipeline
from fitmas.tools.routing import IntentCategory
from fitmas.tools.runtime import ToolExecution, execute_tool_calls

logger = logging.getLogger(__name__)

_SOUL = """\
Tu es FitMAS, un coach multisport IA.
Ton ton: clair, court, precis, confiant, chaleureux sans faux enthousiasme.
Tu parles comme un coach exigeant et calme, jamais comme un bot.
Tu reponds toujours en francais.
Tu ne dis jamais "Bravo continue comme ca" ou autre compliment generique.
Chaque message est contextuel et ancre dans un signal reel.
Tu tutoies toujours l'utilisateur.\
"""

_COACH_SOUL = """\
Tu incarnes le coach personnel de FitMAS.
Tu ecris en francais.
Tu es humain, lucide, calme, precis.
Tu ne sonnes jamais comme un template, jamais comme une pub, jamais comme un bot.
Tu aides a construire une relation de coaching credible des la premiere interaction.\
"""


class MutationDecision(BaseModel):
    mutation_type: str        # "move_session" | "lighten_day" | "swap_sessions" | "update_session" | "replace_session" | "create_session" | "no_change"
    target_session_id: int | None = None
    second_session_id: int | None = None
    target_date: str | None = None
    from_day: str | None = None
    to_day: str | None = None
    new_title: str | None = None
    new_goal: str | None = None
    new_sport_type: str | None = None
    new_session_type: str | None = None
    new_duration_min: int | None = None
    new_intensity: str | None = None
    new_description: str | None = None
    rationale: str            # 1 phrase, pour les change notes
    fitmas_message: str       # message envoye a l'utilisateur


class HealthSignalAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["record_health_signal"]
    health_signal: str
    body_area: str | None = None
    severity: Literal["mild", "moderate", "severe", "unknown"] = "unknown"
    status: Literal["new", "ongoing", "improving", "worsening", "resolved", "unknown"] = "unknown"
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence: str | None = None


class AvailabilityConstraintAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["record_availability"]
    window_text: str
    availability: Literal["unavailable", "limited", "available", "unknown"]
    starts_on: str | None = None
    ends_on: str | None = None
    recurrence: str | None = None
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence: str | None = None


class PreferenceSignalAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["record_preference"]
    preference: str
    polarity: Literal["prefer", "avoid", "like", "dislike", "neutral", "unknown"]
    scope: str | None = None
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence: str | None = None


class ExecutionUpdateAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["record_execution_update"]
    target_ref: str
    target_session_id: int | None = None
    status: Literal["completed", "not_completed", "partially_completed", "unknown"]
    completed: bool | None = None
    sport_type: str | None = None
    duration_min: int | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence: str | None = None


class AcceptPendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["accept_pending"]
    reason: str | None = None
    selected_candidate_id: str | None = None


class RejectPendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["reject_pending"]
    reason: str | None = None


class ModifyPendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["modify_pending"]
    requested_changes: str
    reason: str | None = None


class IgnorePendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["ignore"]
    reason: str | None = None


class NeedsClarificationPendingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["needs_clarification"]
    reason: str
    question: str


MemoryAction = Annotated[
    HealthSignalAction | AvailabilityConstraintAction | PreferenceSignalAction,
    Field(discriminator="type"),
]
PendingResolution = Annotated[
    AcceptPendingResolution
    | RejectPendingResolution
    | ModifyPendingResolution
    | IgnorePendingResolution
    | NeedsClarificationPendingResolution,
    Field(discriminator="type"),
]


class CoachDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    response_type: Literal["reply", "no_change", "mutation_decision", "plan_patch", "requires_confirmation"]
    rationale: str
    fitmas_message: str
    mutation_decision: MutationDecision | None = None
    plan_patch: Any | None = None
    confirmation_reason: str | None = None
    memory_actions: tuple[MemoryAction, ...] = ()
    execution_actions: tuple[ExecutionUpdateAction, ...] = ()
    pending_resolution: PendingResolution | None = None


_DAYS_FR_TO_EN = {
    "lundi": "monday", "mardi": "tuesday", "mercredi": "wednesday",
    "jeudi": "thursday", "vendredi": "friday", "samedi": "saturday",
    "dimanche": "sunday",
}

_TURN_INTENT_TO_PROMPT_INTENT = {
    "close_turn": IntentCategory.CLOSE_TURN,
    "trivial_ack": IntentCategory.CASUAL_CHAT,
    "casual_chat": IntentCategory.CASUAL_CHAT,
    "availability_constraint": IntentCategory.PLAN_NEGOTIATION,
    "plan_mutation": IntentCategory.PLAN_NEGOTIATION,
    "plan_lookup": IntentCategory.PLAN_LOOKUP,
    "execution_report": IntentCategory.EXECUTION_REPORT,
    "health_signal": IntentCategory.PLAN_NEGOTIATION,
    "preference_signal": IntentCategory.PLAN_NEGOTIATION,
}
_CONVERSATION_TOOL_BUDGET = (
    "get_today_context",
    "get_plan_window",
    "resolve_planning_window",
    "get_recent_activities",
    "get_activity_highlights",
    "get_recent_reality_window",
    "get_load_context",
    "get_relevant_facts",
    "get_user_constraints",
    "suggest_replan_candidates",
    "draft_move_session",
    "draft_swap_sessions",
    "draft_replace_session",
    "draft_lighten_day",
    "draft_create_session",
    "validate_plan_patch",
    "validate_week_coherence",
)
_TERMINAL_NO_TOOL_INTENTS = {"close_turn", "trivial_ack", "casual_chat"}
_ALLOWED_MUTATION_TYPES = {
    "move_session",
    "lighten_day",
    "swap_sessions",
    "update_session",
    "replace_session",
    "create_session",
    "no_change",
}
_MUTATIONS_REQUIRING_TARGET_SESSION = {
    "move_session",
    "lighten_day",
    "update_session",
    "replace_session",
}
_NO_CHANGE_ACTION_CLAIM_PATTERNS = (
    "le plan sera ajuste",
    "calendrier sera ajuste",
    "planning sera ajuste",
    "sera reprogramme",
    "je vais ajuster",
    "je vais modifier",
    "je vais construire",
    "je construis",
    "je vais creer",
    "je vais devoir creer",
    "je dois creer",
    "je cree",
    "j ajoute",
    "j ajoute la seance",
    "je pose",
    "je place",
    "je modifie le plan",
    "je modifie le calendrier",
    "je deplace",
    "je libere",
    "je mets a jour",
    "j ai mis a jour",
    "a ete enregistre",
    "est enregistre",
    "est enregistree",
    "nouveau plan coherent",
    "nouvelle seance",
)
_TRUNCATED_MESSAGE_SUFFIXES = (
    "confirme que c est bien",
    "dis moi si",
    "a quelle intensite",
    "ou tu veux",
    "si tu veux",
)
_ALLOWED_COACH_RESPONSE_TYPES = {
    "reply",
    "no_change",
    "mutation_decision",
    "plan_patch",
    "requires_confirmation",
}


def _normalize_day(raw: str | None) -> str | None:
    """Convert French day names to English keys, pass through English names."""
    if not raw:
        return None
    key = raw.strip().lower()
    return _DAYS_FR_TO_EN.get(key, key)


def _prompt_intent_from_turn_context(coach_context: dict | None) -> IntentCategory | None:
    primary_intent = str((coach_context or {}).get("turn_primary_intent") or "")
    return _TURN_INTENT_TO_PROMPT_INTENT.get(primary_intent)


def _is_terminal_no_tool_intent(coach_context: dict | None) -> bool:
    primary_intent = str((coach_context or {}).get("turn_primary_intent") or "")
    return primary_intent in _TERMINAL_NO_TOOL_INTENTS


def _client():
    return gw.client()


def _request_text(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 512) -> str | None:
    """Request text — routes through module-level _request_message (patchable by tests)."""
    response = _request_message(
        system=system,
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
    )
    return _message_text(response)


def _request_message(
    *,
    system: Any,
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 512,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
    thinking: dict[str, Any] | None = None,
    output_config: dict[str, Any] | None = None,
):
    """Send message — delegates to gateway. Tests monkey-patch this function."""
    return gw.request_message(
        system=system, messages=messages, model=model, max_tokens=max_tokens,
        tools=tools, tool_choice=tool_choice, thinking=thinking, output_config=output_config,
    )


def _request_json(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 1024) -> dict | None:
    """Request JSON — routes through module-level _request_text (patchable chain).

    Delegates parsing to llm_gateway._robust_json_loads so every JSON
    entry point (this, gw.request_json, gw.message_json) shares one
    truncation/noise-repair strategy."""
    raw = _request_text(system=system, prompt=prompt, model=model, max_tokens=max_tokens)
    if not raw:
        return None
    return gw._robust_json_loads(raw)


def _request_structured_json(
    *,
    system: str,
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 1024,
) -> dict | None:
    """Request structured JSON through the gateway, preserving test patchability.

    In local/unit contexts without DeepSeek configured, keep the old Anthropic
    path so existing tests can patch `_request_message`. With DeepSeek, use the
    gateway's structured-output path and provider fallback.
    """
    gateway_is_patched = gw.request_structured_json is not _DEFAULT_GATEWAY_STRUCTURED_JSON
    local_json_path_is_patched = (
        _request_json is not _DEFAULT_REQUEST_JSON
        or _request_message is not _DEFAULT_REQUEST_MESSAGE
    )
    if (
        _use_deepseek_openai_structured_output()
        and os.getenv("DEEPSEEK_API_KEY")
        and (gateway_is_patched or not local_json_path_is_patched)
    ):
        result = gw.request_structured_json(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
        )
        if result.provider_fallback_used:
            logger.info(
                "structured_json.provider_fallback provider=%s model=%s error=%s",
                result.provider,
                result.model,
                result.error,
            )
        return result.data
    if len(messages) == 1 and messages[0].get("role") == "user":
        return _request_json(system=system, prompt=str(messages[0].get("content") or ""), model=model, max_tokens=max_tokens)
    raw = _request_text(
        system=system,
        prompt="\n\n".join(str(message.get("content") or "") for message in messages if message.get("role") == "user"),
        model=model,
        max_tokens=max_tokens,
    )
    return gw._robust_json_loads(raw or "") if raw else None


_DEFAULT_REQUEST_MESSAGE = _request_message
_DEFAULT_REQUEST_JSON = _request_json
_DEFAULT_GATEWAY_STRUCTURED_JSON = gw.request_structured_json
_LAST_DECIDE_NONE: dict[str, Any] | None = None


def _use_deepseek_openai_structured_output() -> bool:
    raw = os.getenv("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _log_decide_none(reason: DecideFailureReason, *, prompt_trace: PromptTrace | None = None) -> None:
    global _LAST_DECIDE_NONE
    _LAST_DECIDE_NONE = {
        "reason": reason.value,
        "prompt_trace": prompt_trace.as_dict() if prompt_trace else None,
    }
    logger.info(
        "llm.decide_none reason=%s prompt_trace=%s",
        reason.value,
        _LAST_DECIDE_NONE["prompt_trace"],
    )


def clear_last_decide_none() -> None:
    global _LAST_DECIDE_NONE
    _LAST_DECIDE_NONE = None


def get_last_decide_none() -> dict[str, Any] | None:
    return dict(_LAST_DECIDE_NONE) if _LAST_DECIDE_NONE is not None else None


def _decide_failure_reason_from_exception_type(error_type: str) -> DecideFailureReason:
    if error_type == "timeout":
        return DecideFailureReason.TIMEOUT
    if error_type == "json_parse":
        return DecideFailureReason.INVALID_JSON
    return DecideFailureReason.PROVIDER_ERROR


def decide(
    user_text: str,
    plan_summary: str,
    timeline_summary: str | None = None,
    execution_summary: str | None = None,
    temporal_summary: str | None = None,
    activity_claim_summary: str | None = None,
    signal_summary: str | None = None,
    conversation_history: list[dict] | None = None,
    coach_context: dict | None = None,
    remembered_facts: list[dict] | None = None,
    time_context: dict | None = None,
    tool_context: ToolContext | None = None,
) -> CoachDecision | MutationDecision | None:
    """
    Call the LLM to extract intent and decide a plan mutation.
    Returns None if LLM is unavailable (API key missing or error) -- caller falls back to rules.
    """
    clear_last_decide_none()
    if not _client():
        logger.info("No Anthropic client available — falling back to rules")
        _log_decide_none(DecideFailureReason.NO_CLIENT)
        return None

    resolved_time_context = time_context or build_time_context((coach_context or {}).get("timezone"))
    turn_prompt_intent = _prompt_intent_from_turn_context(coach_context)
    effective_intent = turn_prompt_intent
    prompt_policy = select_conversation_prompt_policy(
        routing_reason=None,
        intent=effective_intent,
    )
    tool_names = () if _is_terminal_no_tool_intent(coach_context) else _tool_budget_for_context(tool_context)
    selected_facts = (coach_context or {}).get("selected_facts") or select_prompt_facts(remembered_facts or [])
    unresolved_execution_followup = (coach_context or {}).get("unresolved_execution_followup")
    prompt_bundle = build_layered_conversation_prompt(
        user_text=user_text,
        prompt_policy=prompt_policy,
        time_block=render_conversation_time_block(resolved_time_context),
        profile_summary=(coach_context or {}).get("profile_summary") or build_profile_summary(remembered_facts or []),
        plan_summary=None,
        timeline_summary=timeline_summary,
        execution_summary=execution_summary,
        temporal_summary=temporal_summary,
        activity_claim_summary=activity_claim_summary,
        signal_summary=signal_summary,
        conversation_history=conversation_history,
        coach_context=coach_context,
        selected_facts=selected_facts,
        unresolved_execution_followup=unresolved_execution_followup,
    )
    prompt = prompt_bundle.prompt
    history_messages_used = prompt_bundle.history_messages_used
    system_prompt = prompt_bundle.system
    prompt_trace = prompt_bundle.trace

    try:
        _remember_invalid_decision(None)
        data = None
        if tool_context is not None and tool_names:
            data = _request_json_with_tools(
                system=system_prompt,
                prompt=prompt,
                tool_context=tool_context,
                tool_names=tool_names,
                context_policy=prompt_policy.name,
                history_messages_used=history_messages_used,
            )
        if data is None:
            data = _request_structured_json(
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
        if not data:
            _log_decide_none(DecideFailureReason.EMPTY_OUTPUT, prompt_trace=prompt_trace)
            return None

        parsed_decision = _parse_llm_decision_payload(data)
        if parsed_decision is None:
            initial_invalid_payload = _last_invalid_decision_payload
            data = _repair_invalid_decision_payload(data=initial_invalid_payload, system=system_prompt, prompt=prompt)
            parsed_decision = _parse_llm_decision_payload(data)
            if parsed_decision is None:
                parsed_decision = _repair_execution_receipt_without_action_decision(
                    data=_last_invalid_decision_payload or data or initial_invalid_payload,
                    coach_context=coach_context,
                )
        if parsed_decision is None:
            data = _request_claude_decision_fallback(system=system_prompt, prompt=prompt)
            parsed_decision = _parse_llm_decision_payload(data)
            if parsed_decision is None:
                parsed_decision = _repair_execution_receipt_without_action_decision(
                    data=_last_invalid_decision_payload or data,
                    coach_context=coach_context,
                )
        if parsed_decision is None:
            _log_decide_none(DecideFailureReason.FALLBACK_FAILED, prompt_trace=prompt_trace)
            return None

        if isinstance(parsed_decision, CoachDecision):
            parsed_decision = _maybe_repair_missing_execution_action_from_followup(
                decision=parsed_decision,
                system=system_prompt,
                prompt=prompt,
                coach_context=coach_context,
            )
            parsed_decision = _maybe_repair_execution_action_consistency(
                decision=parsed_decision,
                system=system_prompt,
                prompt=prompt,
                coach_context=coach_context,
            )
            parsed_decision = _maybe_repair_missing_availability_memory_action(
                decision=parsed_decision,
                system=system_prompt,
                prompt=prompt,
                coach_context=coach_context,
            )
            logger.info(
                "LLM coach decision: %s — %s",
                parsed_decision.response_type,
                parsed_decision.rationale,
            )
            return parsed_decision

        decision = parsed_decision
        logger.info(
            "LLM decision: %s (session=%s, session2=%s, from=%s, to=%s, date=%s) — %s",
            decision.mutation_type, decision.target_session_id, decision.second_session_id, decision.from_day, decision.to_day, decision.target_date,
            decision.rationale,
        )
        return decision

    except Exception as exc:
        error_type = _classify_llm_exception(exc)
        logger.warning(
            "llm.decide_failed type=%s message=%r — falling back to rules",
            error_type,
            str(exc)[:200],
            exc_info=True,
        )
        _log_decide_none(
            _decide_failure_reason_from_exception_type(error_type),
            prompt_trace=prompt_trace if "prompt_trace" in locals() else None,
        )
        return None


def _parse_llm_decision_payload(data: dict[str, Any] | None) -> CoachDecision | MutationDecision | None:
    if not isinstance(data, dict):
        return None
    if "response_type" in data:
        return parse_coach_decision_payload(data)

    # Normalize French day names to English on the legacy wire format.
    data["from_day"] = _normalize_day(data.get("from_day"))
    data["to_day"] = _normalize_day(data.get("to_day"))
    validated = _validate_decision_payload(data)
    if validated is None:
        return None
    return MutationDecision(**validated)


def _validate_decision_payload(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Accept only canonical FitMAS decision payloads.

    Provider JSON mode guarantees syntax, not business contract. This guard
    prevents unknown mutation labels or incomplete write decisions from reaching
    the mutation layer.
    """
    if not isinstance(data, dict):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=not_dict")
        return None
    mutation_type = str(data.get("mutation_type") or "").strip()
    if mutation_type not in _ALLOWED_MUTATION_TYPES:
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=unknown_mutation_type mutation_type=%r", mutation_type)
        return None
    if _looks_like_targetless_replace_create(data, mutation_type=mutation_type):
        data["mutation_type"] = "create_session"
        mutation_type = "create_session"
    if not str(data.get("rationale") or "").strip() and mutation_type != "no_change":
        message_rationale = str(data.get("fitmas_message") or "").strip()
        if message_rationale:
            data["rationale"] = message_rationale[:180]
    if not str(data.get("rationale") or "").strip():
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_rationale mutation_type=%s", mutation_type)
        return None
    fitmas_message = str(data.get("fitmas_message") or "").strip()
    if not fitmas_message:
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_fitmas_message mutation_type=%s", mutation_type)
        return None
    if mutation_type == "no_change" and _message_claims_plan_action_without_mutation(fitmas_message):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=no_change_action_claim mutation_type=%s", mutation_type)
        return None
    if mutation_type == "no_change" and _message_claims_execution_receipt_without_action(
        fitmas_message,
        rationale=str(data.get("rationale") or ""),
    ):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=no_change_execution_receipt_without_action")
        return None
    if _message_violates_coach_voice(fitmas_message):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=coach_voice_violation mutation_type=%s", mutation_type)
        return None
    if _message_has_user_facing_internal_jargon(fitmas_message):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=user_facing_internal_jargon mutation_type=%s", mutation_type)
        return None
    if _message_looks_receipt_style(fitmas_message):
        logger.warning("llm.coach_voice_receipt_style mutation_type=%s message=%r", mutation_type, fitmas_message[:120])
    if _looks_truncated_fitmas_message(fitmas_message):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=truncated_fitmas_message mutation_type=%s", mutation_type)
        return None
    if mutation_type in _MUTATIONS_REQUIRING_TARGET_SESSION and data.get("target_session_id") is None:
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_target_session mutation_type=%s", mutation_type)
        return None
    if mutation_type == "swap_sessions" and (data.get("target_session_id") is None or data.get("second_session_id") is None):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_swap_sessions")
        return None
    if mutation_type == "create_session" and _missing_create_session_fields(data):
        _remember_invalid_decision(data)
        logger.warning("llm.decision_invalid reason=missing_create_session_fields")
        return None
    _remember_invalid_decision(None)
    return data


def parse_coach_decision_payload(data: dict[str, Any] | None) -> CoachDecision | None:
    """Validate the future coach-level decision contract.

    This is intentionally not wired into `decide()` yet. It gives the next
    PlanPatch pipeline a strict parser before the runtime starts relying on it.
    """
    if not isinstance(data, dict):
        _remember_invalid_decision(data)
        logger.warning("llm.coach_decision_invalid reason=not_dict")
        return None
    _remember_invalid_decision(data)
    response_type = str(data.get("response_type") or "").strip()
    if response_type not in _ALLOWED_COACH_RESPONSE_TYPES:
        logger.warning("llm.coach_decision_invalid reason=unknown_response_type response_type=%r", response_type)
        return None
    rationale = str(data.get("rationale") or "").strip()
    if not rationale:
        logger.warning("llm.coach_decision_invalid reason=missing_rationale response_type=%s", response_type)
        return None
    fitmas_message = str(data.get("fitmas_message") or "").strip()
    if not _valid_coach_message(fitmas_message, response_type=response_type):
        return None
    if _has_unknown_memory_action(data.get("memory_actions")):
        logger.warning("llm.coach_decision_invalid reason=unknown_memory_action")
        return None
    if _has_unknown_execution_action(data.get("execution_actions")):
        logger.warning("llm.coach_decision_invalid reason=unknown_execution_action")
        return None

    memory_actions = _normalize_memory_actions(data.get("memory_actions"))
    execution_actions = _normalize_execution_actions(data.get("execution_actions"))
    if not execution_actions and _message_claims_execution_receipt_without_action(fitmas_message, rationale=rationale):
        logger.warning("llm.coach_decision_invalid reason=execution_receipt_without_action")
        return None

    payload: dict[str, Any] = {
        "response_type": response_type,
        "rationale": rationale,
        "fitmas_message": fitmas_message,
        "confirmation_reason": _optional_str(data.get("confirmation_reason")),
        "memory_actions": memory_actions,
        "execution_actions": execution_actions,
        "pending_resolution": data.get("pending_resolution"),
    }
    if response_type == "mutation_decision":
        mutation = _parse_nested_mutation_decision(
            data.get("mutation_decision"),
            fallback_rationale=rationale,
            fallback_fitmas_message=fitmas_message,
        )
        if mutation is None:
            logger.warning("llm.coach_decision_invalid reason=invalid_mutation_decision")
            return None
        payload["mutation_decision"] = mutation
    elif response_type == "plan_patch":
        patch = _parse_nested_plan_patch(data.get("plan_patch"))
        if patch is None:
            logger.warning("llm.coach_decision_invalid reason=invalid_plan_patch")
            return None
        payload["plan_patch"] = patch
    elif response_type == "requires_confirmation":
        if not payload["confirmation_reason"]:
            logger.warning("llm.coach_decision_invalid reason=missing_confirmation_reason")
            return None
        raw_patch = data.get("plan_patch")
        raw_mutation = data.get("mutation_decision")
        if not isinstance(raw_patch, dict) and not isinstance(raw_mutation, dict):
            logger.warning("llm.coach_decision_invalid reason=free_requires_confirmation_without_action")
            return None
        if isinstance(raw_patch, dict):
            patch = _parse_nested_plan_patch(raw_patch)
            if patch is None:
                logger.warning("llm.coach_decision_invalid reason=invalid_confirmation_plan_patch")
                return None
            payload["plan_patch"] = patch
        elif isinstance(raw_mutation, dict):
            mutation = _parse_nested_mutation_decision(
                raw_mutation,
                fallback_rationale=rationale,
                fallback_fitmas_message=fitmas_message,
            )
            if mutation is None:
                logger.warning("llm.coach_decision_invalid reason=invalid_confirmation_mutation_decision")
                return None
            payload["mutation_decision"] = mutation
    try:
        decision = CoachDecision(**payload)
        _remember_invalid_decision(None)
        return decision
    except Exception as exc:
        logger.warning("llm.coach_decision_invalid reason=coach_decision_model_validation_failed error=%s", str(exc)[:240])
        return None


def _parse_nested_mutation_decision(
    raw: Any,
    *,
    fallback_rationale: str | None = None,
    fallback_fitmas_message: str | None = None,
) -> MutationDecision | None:
    if not isinstance(raw, dict):
        return None
    payload = dict(raw)
    if fallback_rationale and not str(payload.get("rationale") or "").strip():
        payload["rationale"] = fallback_rationale
    if fallback_fitmas_message and not str(payload.get("fitmas_message") or "").strip():
        payload["fitmas_message"] = fallback_fitmas_message
    validated = _validate_decision_payload(payload)
    if validated is None:
        return None
    try:
        return MutationDecision(**validated)
    except Exception:
        logger.warning("llm.coach_decision_invalid reason=mutation_model_validation_failed")
        return None


def _parse_nested_plan_patch(raw: Any) -> PlanPatch | None:
    from fitmas.plan_patch import PlanPatch

    if not isinstance(raw, dict):
        return None
    try:
        patch = PlanPatch(**raw)
    except Exception:
        logger.warning("llm.coach_decision_invalid reason=plan_patch_model_validation_failed")
        return None
    if not patch.operations:
        logger.warning("llm.coach_decision_invalid reason=empty_plan_patch")
        return None
    if not _valid_coach_message(patch.coach_message, response_type="plan_patch"):
        return None
    return patch


def _valid_coach_message(message: str, *, response_type: str) -> bool:
    if not message:
        logger.warning("llm.coach_decision_invalid reason=missing_fitmas_message response_type=%s", response_type)
        return False
    if response_type in {"reply", "no_change", "requires_confirmation"} and _message_claims_plan_action_without_mutation(message):
        logger.warning("llm.coach_decision_invalid reason=action_claim_without_patch response_type=%s", response_type)
        return False
    if _message_violates_coach_voice(message):
        logger.warning("llm.coach_decision_invalid reason=coach_voice_violation response_type=%s", response_type)
        return False
    if _message_has_user_facing_internal_jargon(message):
        logger.warning("llm.coach_decision_invalid reason=user_facing_internal_jargon response_type=%s", response_type)
        return False
    if _message_looks_receipt_style(message):
        logger.warning("llm.coach_voice_receipt_style response_type=%s message=%r", response_type, message[:120])
    if _looks_truncated_fitmas_message(message):
        logger.warning("llm.coach_decision_invalid reason=truncated_fitmas_message response_type=%s", response_type)
        return False
    return True


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_memory_actions(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    normalized: list[dict[str, Any]] = []
    allowed_fields = {
        "record_health_signal": {"type", "health_signal", "body_area", "severity", "status", "confidence", "evidence"},
        "record_availability": {"type", "window_text", "availability", "starts_on", "ends_on", "recurrence", "confidence", "evidence"},
        "record_preference": {"type", "preference", "polarity", "scope", "confidence", "evidence"},
    }
    required_fields = {
        "record_health_signal": {"health_signal"},
        "record_availability": {"window_text", "availability"},
        "record_preference": {"preference", "polarity"},
    }
    for item in raw:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("operation_type") or "").strip()
        if action_type not in allowed_fields:
            continue
        cleaned = {key: value for key, value in item.items() if key in allowed_fields[action_type]}
        cleaned["type"] = action_type
        if any(not str(cleaned.get(field) or "").strip() for field in required_fields[action_type]):
            logger.warning("llm.coach_decision_action_dropped action_type=%s reason=missing_required_field", action_type)
            continue
        if "confidence" in cleaned:
            cleaned["confidence"] = _normalize_confidence(cleaned.get("confidence"))
        normalized.append(cleaned)
    return tuple(normalized)


def _has_unknown_memory_action(raw: Any) -> bool:
    if not isinstance(raw, (list, tuple)):
        return False
    allowed = {"record_health_signal", "record_availability", "record_preference"}
    for item in raw:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("operation_type") or "").strip()
        if action_type and action_type not in allowed:
            return True
    return False


def _normalize_execution_actions(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    normalized: list[dict[str, Any]] = []
    allowed_fields = {
        "type",
        "target_ref",
        "target_session_id",
        "status",
        "completed",
        "sport_type",
        "duration_min",
        "confidence",
        "evidence",
    }
    for item in raw:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("operation_type") or "").strip()
        if action_type != "record_execution_update":
            continue
        cleaned = {key: value for key, value in item.items() if key in allowed_fields}
        cleaned["type"] = "record_execution_update"
        completed = _normalize_bool(cleaned.get("completed"))
        if completed is not None:
            cleaned["completed"] = completed
        if not str(cleaned.get("target_ref") or "").strip() and cleaned.get("target_session_id") is not None:
            cleaned["target_ref"] = f"session_id:{cleaned['target_session_id']}"
        cleaned["status"] = _normalize_execution_status(cleaned.get("status"), completed=completed)
        if "confidence" in cleaned:
            cleaned["confidence"] = _normalize_confidence(cleaned.get("confidence"))
        if not str(cleaned.get("target_ref") or "").strip() or cleaned["status"] is None:
            logger.warning("llm.coach_decision_action_dropped action_type=record_execution_update reason=missing_target_or_status")
            continue
        normalized.append(cleaned)
    return tuple(normalized)


def _has_unknown_execution_action(raw: Any) -> bool:
    if not isinstance(raw, (list, tuple)):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or item.get("operation_type") or "").strip()
        if action_type and action_type != "record_execution_update":
            return True
    return False


def _normalize_execution_status(raw: Any, *, completed: Any = None) -> str | None:
    value = str(raw or "").strip().lower()
    if value in {"completed", "done"} or completed is True:
        return "completed"
    if value in {"not_completed", "not done", "not_done", "skipped", "missed", "cancelled", "canceled"} or completed is False:
        return "not_completed"
    if value in {"partially_completed", "partial", "partially done"}:
        return "partially_completed"
    if value == "unknown":
        return "unknown"
    return None


def _message_claims_execution_receipt_without_action(message: str, *, rationale: str) -> bool:
    normalized = _normalize_for_guard(" ".join([message, rationale]))
    if not any(marker in normalized for marker in ("hier", "seance d hier", "seance dhier")):
        return False
    receipt_markers = (
        "vu pour",
        "c est note",
        "vu pour hier",
        "note pour hier",
        "bien note",
        "je note",
        "renfo manque",
        "seance manque",
        "session manque",
        "seance saute",
        "session saute",
        "non fait",
        "ne pas avoir fait",
        "pas avoir fait",
        "pas fait",
        "n est pas fait",
        "n a pas tenu",
        "annule hier",
        "manquee hier",
        "manque la seance",
        "avoir manque",
        "imprevu",
        "pas eu le temps",
        "execution manquee",
    )
    return any(marker in normalized for marker in receipt_markers)


def _repair_execution_receipt_without_action_decision(
    *,
    data: dict[str, Any] | None,
    coach_context: dict | None,
) -> CoachDecision | None:
    """Repair a semantic miss after the LLM already understood the execution receipt.

    This does not parse the user's free text. It only reacts to an invalid LLM
    artifact that already says the previous session was missed, and it requires
    the conversation pipeline to provide the structured follow-up session id.
    """
    if not isinstance(data, dict):
        return None
    fitmas_message = str(data.get("fitmas_message") or "").strip()
    rationale = str(data.get("rationale") or "").strip()
    if not fitmas_message or not rationale:
        return None
    if not _message_claims_execution_receipt_without_action(fitmas_message, rationale=rationale):
        return None
    followup_session_id = _optional_int((coach_context or {}).get("unresolved_execution_followup_session_id"))
    evidence_parts = [part for part in (rationale, fitmas_message) if part]
    evidence = " | ".join(evidence_parts)
    if len(evidence) > 240:
        evidence = evidence[:237].rstrip() + "..."
    repaired_payload = {
        "response_type": "no_change",
        "rationale": rationale,
        "fitmas_message": fitmas_message,
        "execution_actions": [
            {
                "type": "record_execution_update",
                "target_ref": "seance d'hier",
                "target_session_id": followup_session_id,
                "status": "not_completed",
                "completed": False,
                "confidence": 0.85,
                "evidence": evidence,
            }
        ],
        "pending_resolution": data.get("pending_resolution"),
    }
    if followup_session_id is None:
        action = repaired_payload["execution_actions"][0]
        action.pop("target_session_id", None)
        action["confidence"] = 0.8
    decision = parse_coach_decision_payload(repaired_payload)
    if decision is not None:
        logger.info(
            "llm.coach_decision_semantic_repair reason=execution_receipt_without_action target_session_id=%s",
            followup_session_id,
        )
    return decision


def _maybe_repair_missing_execution_action_from_followup(
    *,
    decision: CoachDecision,
    system: str,
    prompt: str,
    coach_context: dict | None,
) -> CoachDecision:
    followup_session_id = _optional_int((coach_context or {}).get("unresolved_execution_followup_session_id"))
    if decision.execution_actions:
        return decision
    normalized_decision_text = _normalize_for_guard(" ".join([decision.fitmas_message, decision.rationale]))
    mentions_recent_execution = (
        followup_session_id is not None
        or "hier" in normalized_decision_text
        or "yesterday" in normalized_decision_text
        or _looks_like_execution_update_artifact(normalized_decision_text)
    )
    if not mentions_recent_execution:
        return decision
    payload = decision.model_dump(mode="json")
    followup_text = str((coach_context or {}).get("unresolved_execution_followup") or "").strip()
    if followup_session_id is not None:
        target_instruction = (
            "Tu ne dois pas inventer de nouvelle seance: la seule cible autorisee est "
            f"target_session_id={followup_session_id}."
        )
    else:
        target_instruction = (
            "Si tu ajoutes une action sans id certain, utilise un target_ref naturel "
            "comme `seance d'hier`; le backend resoudra contre la DB."
        )
    repair_prompt = (
        "Verifie si cette CoachDecision a oublie `execution_actions` pour le suivi execution cible.\n"
        f"{target_instruction}\n"
        "Si le user repond que cette seance cible a ete faite, ajoute `record_execution_update` completed.\n"
        "Si le user repond que cette seance cible n'a pas ete faite, ajoute `record_execution_update` not_completed.\n"
        "Si le user ne repond pas au suivi execution, retourne exactement le meme JSON.\n"
        "Ne change pas les mutations planning ni les memory_actions deja valides.\n"
        "Retourne uniquement un JSON FitMAS CoachDecision valide.\n\n"
        f"SUIVI_EXECUTION_STRUCTURE:\n{followup_text or '(non fourni)'}\n\n"
        f"DECISION_A_VERIFIER:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n"
    )
    repaired = _request_structured_json(
        system=system,
        messages=[{"role": "user", "content": repair_prompt}],
        max_tokens=1024,
    )
    parsed = parse_coach_decision_payload(repaired)
    if parsed is None:
        logger.warning("llm.followup_execution_repair_invalid")
        return decision
    return parsed


def _looks_like_execution_update_artifact(normalized_text: str) -> bool:
    if not normalized_text:
        return False
    non_completion_terms = (
        "pas fait",
        "n a pas fait",
        "non realise",
        "non realisee",
        "manque",
        "manquee",
        "rate",
        "ratee",
        "saute",
        "skipped",
        "not completed",
    )
    execution_subjects = (
        "seance",
        "session",
        "renfo",
        "footing",
        "course",
        "running",
        "natation",
        "swim",
        "velo",
        "cycling",
    )
    return any(term in normalized_text for term in non_completion_terms) and any(
        subject in normalized_text for subject in execution_subjects
    )


def _maybe_repair_execution_action_consistency(
    *,
    decision: CoachDecision,
    system: str,
    prompt: str,
    coach_context: dict | None,
) -> CoachDecision:
    if not bool((coach_context or {}).get("verify_execution_actions")):
        return decision
    if not decision.execution_actions:
        return decision
    payload = decision.model_dump(mode="json")
    repair_prompt = (
        "Verifie la coherence entre `fitmas_message` / `rationale` et `execution_actions`.\n"
        "Tu ne dois pas inventer de nouvelle seance ni changer une mutation planning.\n"
        "Si la phrase dit que la seance est faite mais que l'action dit not_completed, corrige l'action en completed.\n"
        "Si la phrase dit que la seance n'est pas faite mais que l'action dit completed, corrige l'action en not_completed.\n"
        "Si tout est coherent, retourne exactement le meme JSON.\n"
        "Retourne uniquement un JSON FitMAS CoachDecision valide.\n\n"
        f"DECISION_A_VERIFIER:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n"
    )
    repaired = _request_structured_json(
        system=system,
        messages=[{"role": "user", "content": repair_prompt}],
        max_tokens=1024,
    )
    parsed = parse_coach_decision_payload(repaired)
    if parsed is None:
        logger.warning("llm.execution_action_verifier_invalid")
        return decision
    return parsed


def _maybe_repair_missing_availability_memory_action(
    *,
    decision: CoachDecision,
    system: str,
    prompt: str,
    coach_context: dict | None,
) -> CoachDecision:
    if not bool((coach_context or {}).get("repair_memory_actions")):
        return decision
    if any(getattr(action, "type", "") == "record_availability" for action in decision.memory_actions):
        return decision
    intents = {
        str((coach_context or {}).get("turn_primary_intent") or "").strip(),
        *[str(item).strip() for item in ((coach_context or {}).get("turn_secondary_intents") or ())],
    }
    if "availability_constraint" not in intents:
        return decision
    payload = decision.model_dump(mode="json")
    repair_prompt = (
        "Verifie si cette CoachDecision oublie une `memory_actions.record_availability`.\n"
        "Tu es autorise a relire le contexte original comme LLM; le backend ne parse pas ce texte.\n"
        "Si le user exprime une contrainte durable ou datee de disponibilite, ajoute une action `record_availability`.\n"
        "Si aucune contrainte de disponibilite n'est presente, retourne exactement le meme JSON.\n"
        "Ne change pas les mutations planning, pending_resolution ni execution_actions.\n"
        "Retourne uniquement un JSON FitMAS CoachDecision valide.\n\n"
        "FORME record_availability:\n"
        '{"type":"record_availability","window_text":"...","availability":"unavailable|limited|available|unknown",'
        '"starts_on":null,"ends_on":null,"confidence":0.75,"evidence":"..."}\n\n'
        f"DECISION_A_VERIFIER:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n"
    )
    repaired = _request_structured_json(
        system=system,
        messages=[{"role": "user", "content": repair_prompt}],
        max_tokens=1024,
    )
    parsed = parse_coach_decision_payload(repaired)
    if parsed is None:
        logger.warning("llm.availability_memory_repair_invalid")
        return decision
    return parsed


def _normalize_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    value = str(raw or "").strip().lower()
    if value in {"true", "yes", "oui", "1"}:
        return True
    if value in {"false", "no", "non", "0"}:
        return False
    return None


def _normalize_confidence(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    value = str(raw or "").strip().lower()
    if value in {"high", "elevee", "elevée", "strong"}:
        return 0.85
    if value in {"medium", "moyenne", "moderate"}:
        return 0.65
    if value in {"low", "faible"}:
        return 0.4
    try:
        return max(0.0, min(1.0, float(value)))
    except ValueError:
        return 0.75


def _missing_create_session_fields(data: dict[str, Any]) -> bool:
    return (
        not str(data.get("target_date") or "").strip()
        or not str(data.get("new_sport_type") or "").strip()
        or not str(data.get("new_title") or "").strip()
        or data.get("new_duration_min") is None
    )


def _looks_like_targetless_replace_create(data: dict[str, Any], *, mutation_type: str) -> bool:
    return (
        mutation_type == "replace_session"
        and data.get("target_session_id") is None
        and not _missing_create_session_fields(data)
    )


def _message_claims_plan_action_without_mutation(message: str) -> bool:
    normalized = _normalize_for_guard(message)
    return any(pattern in normalized for pattern in _NO_CHANGE_ACTION_CLAIM_PATTERNS)


def _looks_truncated_fitmas_message(message: str) -> bool:
    normalized = _normalize_for_guard(message).rstrip(".!?;:")
    if normalized.endswith(_TRUNCATED_MESSAGE_SUFFIXES):
        return True
    if "confirme" in normalized and message.strip()[-1:] not in {".", "!", "?"}:
        return True
    if message.strip()[-1:] not in {".", "!", "?"} and len(message.strip()) >= 40:
        return True
    return False


# Voice guards (`message_violates_coach_voice`, `message_looks_receipt_style`,
# `normalize_for_voice_guard`) live in `coach_voice` since Chantier 1 — Étape D.
# This module just re-exports them under their legacy private names for callers
# inside this file; new code should import from `fitmas.coach_voice` directly.
_message_violates_coach_voice = coach_voice.message_violates_coach_voice
_message_looks_receipt_style = coach_voice.message_looks_receipt_style
_message_has_user_facing_internal_jargon = coach_voice.message_has_user_facing_internal_jargon
_normalize_for_guard = coach_voice.normalize_for_voice_guard


_last_invalid_decision_payload: dict[str, Any] | None = None


def _remember_invalid_decision(data: dict[str, Any] | None) -> None:
    global _last_invalid_decision_payload
    _last_invalid_decision_payload = dict(data) if isinstance(data, dict) else None


def _repair_invalid_decision_payload(*, data: dict[str, Any] | None, system: str, prompt: str) -> dict | None:
    """Retry once with the invalid payload and the FitMAS decision contract."""
    if not data:
        return None
    repair_prompt = (
        "Le payload LLM suivant est invalide pour FitMAS.\n"
        "Repare-le en JSON FitMAS canonique sans inventer de session id, de seance ou de fait.\n"
        "Preserve les actions memoire/execution deja justes si elles sont compatibles avec le contexte.\n"
        "Si le message utilisateur indique seulement qu'une seance n'a pas ete faite, retourne response_type=\"no_change\" + execution_actions, pas requires_confirmation.\n"
        "Si tu ne peux pas produire une mutation planning valide, retourne no_change.\n\n"
        "CONTRAT:\n"
        "- format prefere: CoachDecision avec response_type=reply|no_change|mutation_decision|plan_patch|requires_confirmation\n"
        "- mutation_type autorises: move_session, lighten_day, swap_sessions, update_session, replace_session, create_session, no_change\n"
        "- rationale et fitmas_message obligatoires et non vides\n"
        "- execution_actions autorise record_execution_update: target_ref, target_session_id?, status=completed|not_completed|partially_completed|unknown, completed?, sport_type?, duration_min?, confidence, evidence?\n"
        "- memory_actions autorise record_health_signal, record_availability, record_preference\n"
        "- pending_resolution autorise accept_pending, reject_pending, modify_pending, ignore, needs_clarification\n"
        "- pending_resolution.accept_pending peut porter selected_candidate_id pour choisir une option plan_patch_choice\n"
        "- pending_resolution.modify_pending exige requested_changes; reason est optionnel\n"
        "- requires_confirmation exige confirmation_reason et sert aux mutations planning risquees, pas aux updates execution simples\n"
        "- move_session/lighten_day/update_session/replace_session exigent target_session_id\n"
        "- swap_sessions exige target_session_id et second_session_id\n"
        "- create_session exige target_date, new_sport_type, new_title, new_duration_min\n"
        "- mapping utile: downgrade/unplanned_skip/replace sans session claire -> lighten_day seulement si target_session_id existe, sinon no_change\n\n"
        "GARDE-FOUS MESSAGE:\n"
        "- si mutation_type=no_change, ne promets jamais que le plan est ajuste, deplace, libere ou mis a jour\n"
        "- si mutation_type=no_change, ne dis pas que tu vas construire un plan ou creer une seance\n"
        "- si mutation_type=no_change, fitmas_message doit rester neutre: comprehension, clarification, ou besoin de lire le plan\n"
        "- tutoie toujours l'utilisateur: jamais vous/vos/votre\n"
        "- ne laisse jamais fitmas_message tronque ou fini sur une demande incomplete comme \"confirme que c'est bien\"\n"
        "- ne rajoute pas une question si la reponse peut etre une clarification courte\n\n"
        f"PAYLOAD_INVALIDE:\n{json.dumps(data, ensure_ascii=False)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n\n"
        "Retourne uniquement le JSON repare."
    )
    repaired = _request_structured_json(
        system=system,
        messages=[{"role": "user", "content": repair_prompt}],
        max_tokens=1024,
    )
    return _downgrade_free_confirmation_payload(repaired)


def _request_claude_decision_fallback(*, system: str, prompt: str) -> dict | None:
    """Use Claude as a schema fallback after a structured DeepSeek payload failed validation."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    result = gw.request_structured_json(
        system=system,
        messages=[{"role": "user", "content": prompt}],
        model="claude-haiku-4-5-20251001",
        fallback_model="claude-haiku-4-5-20251001",
        provider="claude",
    )
    logger.info(
        "structured_json.schema_fallback provider=%s model=%s ok=%s error=%s",
        result.provider,
        result.model,
        result.data is not None,
        result.error,
    )
    return result.data


def _classify_llm_exception(exc: BaseException) -> str:
    """Classify a raised exception so operators can triage failures.

    Returns a short stable label (`timeout`, `rate_limit`, `bad_request`,
    `auth`, `connection`, `api_other`, `json_parse`, `unknown`). The
    labels are log-only — `decide()` still returns None for every case.
    """
    return gw.classify_llm_exception(exc)


def _tool_budget_for_context(tool_context: ToolContext | None) -> tuple[str, ...]:
    if tool_context is None:
        return ()
    if tool_context.pipeline == "conversation":
        return _CONVERSATION_TOOL_BUDGET
    return ()


def _deepseek_tool_thinking_kwargs() -> dict[str, dict[str, str]]:
    if not os.getenv("DEEPSEEK_API_KEY"):
        return {}
    raw_enabled = str(os.getenv("FITMAS_DEEPSEEK_TOOL_THINKING") or "").strip().lower()
    if raw_enabled not in {"1", "true", "yes", "on", "enabled"}:
        return {}
    effort = str(os.getenv("FITMAS_DEEPSEEK_TOOL_THINKING_EFFORT") or "high").strip().lower()
    if effort not in {"high", "max"}:
        effort = "high"
    return {
        "thinking": {"type": "enabled"},
        "output_config": {"effort": effort},
    }


def _request_json_with_tools(
    *,
    system: str,
    prompt: str,
    tool_context: ToolContext,
    tool_names: tuple[str, ...],
    context_policy: str,
    history_messages_used: int,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 1024,
) -> dict | None:
    tools = list_tools_for_pipeline(tool_context.pipeline, tool_names=tool_names)
    if not tools:
        return None
    started_at = perf_counter()
    prompt_char_count = len(prompt)
    tool_count_offered = len(tools)
    messages = [{"role": "user", "content": prompt}]
    max_tool_rounds = 3
    max_tool_calls_total = 6
    tool_rounds = 0
    tool_calls_used = 0
    tool_executions: list[ToolExecution] = []
    prompt_token_values: list[int | None] = []
    response_token_values: list[int | None] = []
    response = _request_message(
        system=system,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice={"type": "auto"},
        **_deepseek_tool_thinking_kwargs(),
    )
    if response is None:
        _log_tool_session_trace(
            pipeline=tool_context.pipeline,
            tool_offered=True,
            context_policy=context_policy,
            tool_requested=False,
            tool_called=False,
            tool_success=False,
            fallback_used=True,
            llm_round_trips=1,
            tool_count_offered=tool_count_offered,
            history_messages_used=history_messages_used,
            prompt_char_count=prompt_char_count,
            total_duration_ms=_elapsed_ms(started_at),
            response_stop_reason="initial_request_failed",
        )
        return None

    round_trips = 1
    while True:
        stop_reason = str(getattr(response, "stop_reason", "") or "")
        prompt_token_values.append(_usage_value(response, "input_tokens"))
        response_token_values.append(_usage_value(response, "output_tokens"))

        if stop_reason != "tool_use":
            data = _message_json(response)
            raw_text_for_repair = _message_text(response)
            if tool_executions and data is None:
                retry_response = _retry_tool_followup_json_format(
                    system=system,
                    messages=messages,
                    response=response,
                    model=model,
                    max_tokens=max_tokens,
                )
                if retry_response is not None:
                    round_trips += 1
                    prompt_token_values.append(_usage_value(retry_response, "input_tokens"))
                    response_token_values.append(_usage_value(retry_response, "output_tokens"))
                    retry_data = _message_json(retry_response)
                    if retry_data is not None:
                        data = retry_data
                    else:
                        raw_text_for_repair = _message_text(retry_response) or raw_text_for_repair
            if tool_executions and data is None:
                data = _repair_decision_json_from_text(
                    raw_text_for_repair,
                    model=model,
                    context_prompt=prompt,
                    tool_result_summary=_repair_tool_result_summary(tool_executions),
                )
            _log_tool_session_trace(
                pipeline=tool_context.pipeline,
                tool_name=_tool_execution_names(tool_executions),
                tool_offered=True,
                context_policy=context_policy,
                tool_requested=bool(tool_executions),
                tool_called=_any_tool_called(tool_executions),
                tool_latency_ms=_sum_tool_latency(tool_executions),
                tool_success=(
                    data is not None
                    and (not tool_executions or _all_tool_results_ok(tool_executions))
                ),
                tool_error=(
                    _tool_errors(tool_executions)
                    if data is not None
                    else (_tool_errors(tool_executions) or "tool followup response was not valid JSON")
                ),
                fallback_used=data is None,
                llm_round_trips=round_trips,
                tool_count_offered=tool_count_offered,
                history_messages_used=history_messages_used,
                prompt_char_count=prompt_char_count,
                prompt_tokens_estimate=_sum_optional_ints(prompt_token_values),
                response_tokens_estimate=_sum_optional_ints(response_token_values),
                total_duration_ms=_elapsed_ms(started_at),
                response_stop_reason=stop_reason or "end_turn",
            )
            return data

        tool_use_blocks = _tool_use_blocks(response)
        if not tool_use_blocks:
            data = _message_json(response)
            _log_tool_session_trace(
                pipeline=tool_context.pipeline,
                tool_offered=True,
                context_policy=context_policy,
                tool_requested=True,
                tool_called=_any_tool_called(tool_executions),
                tool_success=data is not None,
                tool_error="tool_use stop_reason without tool block",
                fallback_used=True,
                llm_round_trips=round_trips,
                tool_count_offered=tool_count_offered,
                history_messages_used=history_messages_used,
                prompt_char_count=prompt_char_count,
                prompt_tokens_estimate=_sum_optional_ints(prompt_token_values),
                response_tokens_estimate=_sum_optional_ints(response_token_values),
                total_duration_ms=_elapsed_ms(started_at),
                response_stop_reason=stop_reason or "tool_use",
            )
            return data

        tool_rounds += 1
        remaining_tool_budget = max(0, max_tool_calls_total - tool_calls_used)
        tool_calls = [
            ToolCall(tool_name=str(getattr(block, "name", "")), arguments=dict(getattr(block, "input", {}) or {}))
            for block in tool_use_blocks
        ]
        round_executions = execute_tool_calls(
            tool_calls,
            context=tool_context,
            max_tools=remaining_tool_budget,
            llm_round_trips=round_trips + 1,
            prompt_tokens_estimate=_sum_optional_ints(prompt_token_values),
            response_tokens_estimate=_sum_optional_ints(response_token_values),
        )
        tool_calls_used += min(len(tool_calls), remaining_tool_budget)
        tool_executions.extend(round_executions)
        messages.append({"role": "assistant", "content": _serialize_content_blocks(getattr(response, "content", []))})
        messages.append({"role": "user", "content": _tool_followup_content(tool_use_blocks, round_executions)})

        allow_more_tools = tool_rounds < max_tool_rounds and tool_calls_used < max_tool_calls_total
        response = _request_message(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            tools=tools if allow_more_tools else None,
            tool_choice={"type": "auto"} if allow_more_tools else None,
            **_deepseek_tool_thinking_kwargs(),
        )
        round_trips += 1
        if response is None:
            _log_tool_session_trace(
                pipeline=tool_context.pipeline,
                tool_name=_tool_execution_names(tool_executions),
                tool_offered=True,
                context_policy=context_policy,
                tool_requested=True,
                tool_called=_any_tool_called(tool_executions),
                tool_latency_ms=_sum_tool_latency(tool_executions),
                tool_success=False,
                tool_error=_tool_errors(tool_executions) or "tool followup request failed",
                fallback_used=True,
                llm_round_trips=round_trips,
                tool_count_offered=tool_count_offered,
                history_messages_used=history_messages_used,
                prompt_char_count=prompt_char_count,
                prompt_tokens_estimate=_sum_optional_ints(prompt_token_values),
                response_tokens_estimate=_sum_optional_ints(response_token_values),
                total_duration_ms=_elapsed_ms(started_at),
                response_stop_reason="followup_request_failed",
            )
            return None

    _log_tool_session_trace(
        pipeline=tool_context.pipeline,
        tool_name=_tool_execution_names(tool_executions),
        tool_offered=True,
        context_policy=context_policy,
        tool_requested=True,
        tool_called=_any_tool_called(tool_executions),
        tool_latency_ms=_sum_tool_latency(tool_executions),
        tool_success=False,
        tool_error=_tool_errors(tool_executions) or "tool loop exhausted",
        fallback_used=True,
        llm_round_trips=round_trips,
        tool_count_offered=tool_count_offered,
        history_messages_used=history_messages_used,
        prompt_char_count=prompt_char_count,
        prompt_tokens_estimate=_sum_optional_ints(prompt_token_values),
        response_tokens_estimate=_sum_optional_ints(response_token_values),
        total_duration_ms=_elapsed_ms(started_at),
        response_stop_reason="tool_loop_exhausted",
    )
    return None


def _retry_tool_followup_json_format(
    *,
    system: str,
    messages: list[dict[str, Any]],
    response: Any,
    model: str,
    max_tokens: int,
) -> Any | None:
    raw_text = _message_text(response)
    if not raw_text:
        return None
    retry_messages = list(messages)
    retry_messages.append({"role": "assistant", "content": _serialize_content_blocks(getattr(response, "content", []))})
    retry_messages.append(
        {
            "role": "user",
            "content": (
                "Ta derniere reponse a un format incorrect: ce n'est pas un JSON FitMAS valide. "
                "Les tools sont termines pour ce tour; n'appelle aucun tool supplementaire. "
                "Garde exactement la meme intention et les memes faits, mais retourne uniquement "
                "un CoachDecision JSON valide. Pas de prose hors JSON. N'invente aucun id, aucune seance, aucun commit."
            ),
        }
    )
    return _request_message(
        system=system,
        messages=retry_messages,
        model=model,
        max_tokens=max_tokens,
        **_deepseek_tool_thinking_kwargs(),
    )


def _tool_result_blocks(tool_use_blocks: list[Any], tool_executions: list[ToolExecution]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for tool_use_block, execution in zip(tool_use_blocks, tool_executions):
        result = execution.result
        blocks.append(
            {
                "type": "tool_result",
                "tool_use_id": getattr(tool_use_block, "id", ""),
                "content": json.dumps(
                    {
                        "summary": result.summary,
                        "payload": result.payload,
                        "error": result.error,
                    },
                    ensure_ascii=False,
                ),
                "is_error": result.status != "ok",
            }
        )
    return blocks


def _tool_followup_content(tool_use_blocks: list[Any], tool_executions: list[ToolExecution]) -> list[dict[str, Any]]:
    return [
        *_tool_result_blocks(tool_use_blocks, tool_executions),
        {
            "type": "text",
            "text": (
                "Tu peux appeler d'autres tools si une information manque. "
                "Si un tool draft_* retourne payload.patch, ne dis jamais que c'est applique; "
                "copie ce patch dans un CoachDecision response_type=plan_patch ou requires_confirmation. "
                "Si tu as valide un patch significatif, utilise aussi validate_week_coherence quand disponible. "
                "Si tu as assez d'information, retourne maintenant uniquement un JSON FitMAS CoachDecision valide; "
                "pas de prose hors JSON."
            ),
        },
    ]


def _tool_execution_names(tool_executions: list[ToolExecution]) -> str | None:
    names = [execution.result.tool_name for execution in tool_executions if execution.result.tool_name]
    return ",".join(names) if names else None


def _any_tool_called(tool_executions: list[ToolExecution]) -> bool:
    return any(execution.trace.tool_called for execution in tool_executions)


def _all_executed_tools_ok(tool_executions: list[ToolExecution]) -> bool:
    called = [execution for execution in tool_executions if execution.trace.tool_called]
    return bool(called) and all(execution.result.status == "ok" for execution in called)


def _all_tool_results_ok(tool_executions: list[ToolExecution]) -> bool:
    return bool(tool_executions) and all(execution.result.status == "ok" for execution in tool_executions)


def _sum_tool_latency(tool_executions: list[ToolExecution]) -> int | None:
    values = [execution.trace.tool_latency_ms for execution in tool_executions if execution.trace.tool_latency_ms is not None]
    return sum(values) if values else None


def _tool_errors(tool_executions: list[ToolExecution]) -> str | None:
    errors = [execution.result.error for execution in tool_executions if execution.result.error]
    return "; ".join(errors) if errors else None


def _sum_optional_ints(values: list[int | None]) -> int | None:
    present = [int(value) for value in values if value is not None]
    return sum(present) if present else None


def _repair_decision_json_from_text(
    raw_text: str | None,
    *,
    model: str = "claude-haiku-4-5-20251001",
    context_prompt: str | None = None,
    tool_result_summary: str | None = None,
) -> dict | None:
    """Convert a prose decision-like answer into canonical JSON once."""
    if not raw_text:
        return None
    if _looks_like_provider_tool_markup(raw_text):
        return None
    context_block = f"\nCONTEXTE_ORIGINAL:\n{context_prompt}\n" if context_prompt else ""
    tools_block = f"\nRESULTATS_TOOLS:\n{tool_result_summary}\n" if tool_result_summary else ""
    prompt = (
        "Convertis cette reponse coach en JSON FitMAS canonique.\n"
        "N'invente pas de champ, de session id, ni de mutation absente de la reponse brute.\n"
        "Format prefere: CoachDecision avec response_type, rationale, fitmas_message, memory_actions, execution_actions et pending_resolution si utile.\n"
        "Si l'action planning n'est pas claire, retourne response_type=\"no_change\".\n"
        "Si la reponse brute dit qu'une seance n'a pas ete faite, retourne no_change + execution_actions record_execution_update.\n"
        "Ne retourne jamais un simple mutation_type=no_change quand la reponse brute reconnait une execution faite/non faite: cela perdrait l'action execution.\n"
        "N'ajoute sport_type dans execution_actions que si le contexte le rend certain.\n"
        "execution_actions.record_execution_update: type, target_ref, target_session_id?, status=completed|not_completed|partially_completed|unknown, completed?, sport_type?, duration_min?, confidence?, evidence?.\n"
        "mutation_type autorises: move_session, lighten_day, swap_sessions, update_session, replace_session, create_session, no_change.\n"
        "Compat legacy autorisee seulement si aucune action memoire/execution/pending n'est necessaire.\n"
        "Champs requis: response_type, rationale, fitmas_message.\n"
        "Pour move_session/lighten_day/update_session/replace_session, target_session_id doit etre present si la reponse parle d'une seance existante.\n\n"
        "Pour create_session, target_date, new_sport_type, new_title et new_duration_min sont obligatoires.\n\n"
        "GARDE-FOUS:\n"
        "- n'utilise jamais response_type=requires_confirmation sans plan_patch ou mutation_decision structure\n"
        "- si la reponse brute propose une option a confirmer mais ne contient pas de patch structure, retourne no_change avec une question courte\n"
        "- si tu retournes no_change, ne promets pas que le plan est ajuste, modifie, deplace, libere ou mis a jour\n"
        "- si tu retournes no_change, ne dis pas que tu vas construire un plan ou creer une seance\n"
        "- si la reponse brute promet une action mais ne donne pas de mutation valide, reformule en clarification neutre\n"
        "- tutoie toujours l'utilisateur: jamais vous/vos/votre\n"
        "- fitmas_message doit etre complet, court, et ne doit pas finir sur une phrase coupee\n"
        "- ne rajoute pas de nouvelle question sauf si la reponse brute en contient deja une claire\n\n"
        "EXEMPLE OBLIGATOIRE:\n"
        "REPONSE_BRUTE: \"Hier n'a pas tenu, compris. Le footing de ce matin est toujours en place.\"\n"
        "JSON: {\"response_type\":\"no_change\",\"rationale\":\"execution manquee comprise sans mutation planning\",\"fitmas_message\":\"Hier n'a pas tenu, compris. Le footing de ce matin reste en place.\",\"execution_actions\":[{\"type\":\"record_execution_update\",\"target_ref\":\"seance d'hier\",\"status\":\"not_completed\",\"completed\":false,\"confidence\":0.8,\"evidence\":\"Hier n'a pas tenu\"}]}\n\n"
        f"{context_block}"
        f"{tools_block}"
        "REPONSE_BRUTE:\n"
        f"{raw_text}\n\n"
        "Retourne uniquement le JSON."
    )
    data = _request_structured_json(
        system="Tu repars strictement des mots fournis et tu retournes un JSON valide uniquement.",
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=1024,
    )
    return _downgrade_free_confirmation_payload(data)


def _downgrade_free_confirmation_payload(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return data
    if str(data.get("response_type") or "").strip() != "requires_confirmation":
        return data
    if isinstance(data.get("plan_patch"), dict) or isinstance(data.get("mutation_decision"), dict):
        return data
    repaired = dict(data)
    repaired["response_type"] = "no_change"
    repaired["confirmation_reason"] = None
    return repaired


def _repair_tool_result_summary(tool_executions: list[ToolExecution]) -> str | None:
    lines = []
    for execution in tool_executions:
        result = execution.result
        payload_json = json.dumps(result.payload, ensure_ascii=False)
        if len(payload_json) > 2500:
            payload_json = payload_json[:2500] + "...[truncated]"
        if result.summary or result.payload:
            lines.append(
                f"- {result.tool_name}: {result.summary or '(pas de resume)'}\n"
                f"  payload: {payload_json}"
            )
    return "\n".join(lines) or None


def _looks_like_provider_tool_markup(raw_text: str) -> bool:
    normalized = raw_text.strip().lower()
    return (
        "<｜dsml｜tool_calls>" in normalized
        or "<｜dsml｜invoke" in normalized
        or "invoke name=" in normalized
    )


def make_plan_summary(days: list) -> str:
    """Build a compact plan summary to inject into the LLM prompt."""
    lines = []
    for d in days:
        lines.append(
            f"- {d.label} ({d.day}): [{getattr(d, 'sport_type', 'running')}] {d.session_title} — {d.session_goal} "
            f"(priorite: {d.priority}, flexibilite: {d.flexibility})"
        )
    return "\n".join(lines)


_message_text = gw.message_text
_message_json = gw.message_json
_first_tool_use_block = gw.first_tool_use_block
_serialize_content_blocks = gw.serialize_content_blocks


def _tool_use_blocks(response: Any) -> list[Any]:
    return [
        block
        for block in (getattr(response, "content", []) or [])
        if getattr(block, "type", None) == "tool_use"
    ]
_usage_value = gw.usage_value
_sum_ints = gw.sum_ints
_elapsed_ms = gw.elapsed_ms


def _log_tool_session_trace(
    *,
    pipeline: str,
    tool_offered: bool,
    tool_requested: bool,
    tool_called: bool,
    tool_success: bool,
    context_policy: str | None = None,
    tool_name: str | None = None,
    tool_latency_ms: int | None = None,
    tool_error: str | None = None,
    fallback_used: bool = False,
    llm_round_trips: int = 1,
    tool_count_offered: int | None = None,
    history_messages_used: int | None = None,
    prompt_char_count: int | None = None,
    prompt_tokens_estimate: int | None = None,
    response_tokens_estimate: int | None = None,
    total_duration_ms: int | None = None,
    response_stop_reason: str | None = None,
) -> None:
    trace = build_tool_trace(
        pipeline=pipeline,
        tool_name=tool_name,
        tool_offered=tool_offered,
        context_policy=context_policy,
        tool_requested=tool_requested,
        tool_called=tool_called,
        tool_latency_ms=tool_latency_ms,
        tool_success=tool_success,
        tool_error=tool_error,
        fallback_used=fallback_used,
        llm_round_trips=llm_round_trips,
        tool_count_offered=tool_count_offered,
        history_messages_used=history_messages_used,
        prompt_char_count=prompt_char_count,
        prompt_tokens_estimate=prompt_tokens_estimate,
        response_tokens_estimate=response_tokens_estimate,
        total_duration_ms=total_duration_ms,
        response_stop_reason=response_stop_reason,
    )
    log_tool_trace(trace)
def make_timeline_summary(sessions: list) -> str:
    lines = []
    for session in sessions:
        day = getattr(session, "day", "")
        date_value = getattr(session, "scheduled_date", "")
        sport_type = getattr(session, "sport_type", "running")
        session_type = getattr(session, "session_type", "")
        status = getattr(session, "completion_status", "planned")
        slot = _timeline_slot_kind(session)
        movable_target = slot == "free_flexible"
        status_key = str(status or "").strip().lower()
        can_swap_with_training = slot in {"training", "free_flexible"} and status_key not in {"done", "skipped", "canceled"}
        swappable = can_swap_with_training
        lines.append(
            f"- id={getattr(session, 'id', '?')} | date={date_value} | day={day} | "
            f"slot={slot} | movable_target={str(movable_target).lower()} | "
            f"swappable={str(swappable).lower()} | "
            f"can_swap_with_training={str(can_swap_with_training).lower()} | [{sport_type}/{session_type}] "
            f"{getattr(session, 'session_title', '')} | goal={getattr(session, 'session_goal', '')} | status={status}"
        )
    return "\n".join(lines)


def _timeline_slot_kind(session: object) -> str:
    sport = str(getattr(session, "sport_type", "") or "").strip().lower()
    session_type = str(getattr(session, "session_type", "") or "").strip().lower()
    status = str(getattr(session, "completion_status", "") or "").strip().lower()
    if status in {"done", "skipped", "canceled"}:
        return "closed"
    recovery_like = sport in {"rest", "off", ""} or session_type in {"rest", "recovery", "mobility"}
    if recovery_like:
        return "free_flexible"
    return "training"


def preview_coach_voice(context: dict, *, time_context: dict | None = None) -> list[str]:
    resolved_time_context = time_context or build_time_context(context.get("timezone"))
    coach = build_coach_profile(context)
    prompt = f"""{render_time_context(resolved_time_context)}
Contexte user:
- cap: {build_goal_summary(context)}
- sports: {", ".join(context['sports'])}
- realite de semaine: {context.get('weekly_structure_notes', '')}
- etat actuel: {context.get('current_state_notes', '') or 'encore en cours de calibration'}
- preset: {coach['coach_preset_label']}
- style: {coach['coach_style']}
- relation voulue: {coach['coach_relationship']}
- ce que le coach doit faire: {coach['coach_do']}
- ce qu'il ne doit jamais faire: {coach['coach_dont']}
- ame libre: {coach['coach_soul']}

Genere exactement 3 messages courts que ce coach pourrait envoyer.
Scenario:
- la semaine vient d'etre comprise
- mardi parait fragile
- il faut montrer de la presence sans surjouer

Contraintes:
- 1 ou 2 phrases max par message
- chaque proposition doit avoir une saveur differente mais rester dans la meme ame
- pas de compliment generique
- reponds en JSON: {{"messages": ["...", "...", "..."]}}"""

    data = _request_json(system=_COACH_SOUL, prompt=prompt, max_tokens=700)
    if data and isinstance(data.get("messages"), list) and len(data["messages"]) >= 3:
        return [str(message).strip() for message in data["messages"][:3]]

    return _fallback_voice_preview(context)


def formulate_onboarding_recap(context: dict, *, time_context: dict | None = None) -> str:
    resolved_time_context = time_context or build_time_context(context.get("timezone"))
    coach = build_coach_profile(context)
    prompt = f"""{render_time_context(resolved_time_context)}
Tu dois rediger le recap final d'un onboarding.

Contexte:
- sports: {", ".join(context['sports'])}
- cap: {build_goal_summary(context)}
- realite de semaine: {context['weekly_structure_notes']}
- etat actuel: {context.get('current_state_notes', '') or 'encore a lire sur les premieres semaines'}
- contraintes: {" ; ".join(context['constraints']) or "aucune precisee"}
- preferences: {" ; ".join(context['preferences']) or "aucune precisee"}
- coach: {coach['coach_name']} / preset {coach['coach_preset_label']} / style {coach['coach_style']}
- ame: {coach['coach_soul']}

Ecris un recap court en 4 a 6 lignes:
- ce que FitMAS a compris
- ce que tu protegeras des le debut
- ce qui reste encore a clarifier si besoin
- le ton du coach

Pas de markdown complexe. Pas de phrase creuse."""

    text = _request_text(system=_COACH_SOUL, prompt=prompt, max_tokens=320)
    if text:
        return text
    return _fallback_recap(context)


def formulate_week_plan(
    planner_output: dict,
    user_profile: dict,
    coach_profile: dict,
    *,
    time_context: dict | None = None,
) -> dict:
    resolved_time_context = time_context or build_time_context(user_profile.get("timezone") or coach_profile.get("timezone"))
    sports_set = set(user_profile.get("sports", []))
    knowledge_block = load_sport_knowledge(sports_set, max_tokens=1500)
    planning_context = planner_output.get("planning_context") or {}
    planning_context_block = ""
    if planning_context:
        planning_context_block = (
            "\nDecision de planning deja prise hors LLM:\n"
            f"- planning_mode: {planning_context.get('planning_mode')}\n"
            f"- weekly_target_tss: {planning_context.get('weekly_target_tss')}\n"
            f"- key_session_count: {planning_context.get('key_session_count')}\n"
            f"- strength_session_count: {planning_context.get('strength_session_count')}\n"
            f"- long_session: {planning_context.get('long_session')}\n"
            f"- rationale: {' ; '.join(planning_context.get('rationale') or [])}\n"
            f"- adaptations: {' ; '.join(planning_context.get('adaptations') or [])}\n"
        )
    prompt = f"""{render_time_context(resolved_time_context)}
Tu dois enrichir un squelette de semaine multisport pour que chaque seance soit directement utilisable en situation reelle.

User:
- objectif: {user_profile['primary_objective']}
- sports: {", ".join(user_profile['sports'])}
- realite de semaine: {user_profile['weekly_structure_notes']}
- contraintes: {" ; ".join(user_profile['constraints']) or "aucune precisee"}
- preferences: {" ; ".join(user_profile['preferences']) or "aucune precisee"}

Coach:
- nom: {coach_profile['coach_name']}
- style: {coach_profile['coach_style']}
- relation: {coach_profile['coach_relationship']}
- fait: {coach_profile['coach_do']}
- ne fait jamais: {coach_profile['coach_dont']}
- ame: {coach_profile['coach_soul']}
{planning_context_block}

Connaissances sport (utilise comme reference pour formuler les seances):
{knowledge_block}

Squelette:
{json.dumps(planner_output, ensure_ascii=False)}

Retourne un JSON avec:
- intention
- summary
- days: liste de 7 objets dans le meme ordre

Chaque day doit contenir:
- day
- session_title: titre court et precis (ex: "Footing endurance 45min zone 2", "Fractionne 8x400m R1min", "Natation technique 4x200m")
- session_goal: objectif clair en 1 phrase actionnable
- session_description: le deroulement complet de la seance, structure en blocs. C'est le champ le plus important.
- session_note: note de contexte sur la place de la seance dans la semaine (1-2 phrases)
- watch_title
- watch_detail

REGLE CRITIQUE — session_description:
Chaque session_description doit etre un plan de seance concret que l'utilisateur peut suivre tel quel.
Format: blocs separes par des retours a la ligne, avec durees/distances/intensites.

Exemples par sport:
- Running easy: "Echauffement 10min marche/trot\\n30min footing zone 2 (allure confortable, on peut parler)\\n5min retour au calme marche"
- Running quality: "Echauffement 15min footing progressif\\n8x400m a allure 10k, recup 1min trot\\n10min retour au calme footing lent"
- Running long: "10min trot lent\\n55min footing endurance zone 2 (regulier, pas d'acceleration)\\n5min marche retour calme\\nObjectif: finir frais, pas vide"
- Natation technique: "200m echauffement nage libre souple\\n4x100m crawl technique (rattrapé, poings fermés, amplitude) R20s\\n4x50m sprint 80% R30s\\n200m retour calme dos/brasse"
- Natation easy: "200m echauffement varié (crawl/dos)\\n8x50m crawl allure reguliere R15s\\n4x25m au choix\\n100m souple retour calme"
- Velo endurance: "15min echauffement progressif\\n50min zone 2 cadence 85-95rpm\\n10min retour calme moulinette"
- Escalade bloc: "15min echauffement articulaire + dalle facile\\n45min blocs projet (3-4 essais par bloc, repos complet entre)\\n20min volume facile\\n10min etirements"
- Renfo/strength: "Echauffement 5min mobilite\\n3x12 squats + 3x10 pompes + 3x30s gainage\\n2x15 fentes + 2x10 rowing\\nEtirements 5min"
- Repos: pas de session_description (laisser vide)

Adapte les distances, allures et series au niveau de l'utilisateur et a la duree prevue dans le squelette.
Ne mets JAMAIS de description vague comme "Fais ta seance normalement" ou "Seance de natation classique".

Regles:
- ne change jamais sport_type, session_type, duration_min, intensity, load_score, priority, flexibility
- ancre la voix dans le coach
- pas de phrases generiques
- session_title doit etre plus precis que le squelette (ajouter volume, allure, format)
- session_goal doit dire ce que la seance construit concretement
- session_description est le coeur: plan de seance structuré, blocs clairs, actionnable immediatement"""

    data = _request_json(system=_COACH_SOUL, prompt=prompt, model="claude-sonnet-4-6", max_tokens=3000)
    if data:
        try:
            return _merge_week_enrichment(planner_output, data)
        except Exception:
            logger.exception("Failed to merge enriched week plan")
    return _fallback_week_plan(planner_output, coach_profile)


def _sanitize_coach_text(text: str, fallback: str) -> str:
    """Reject LLM output that looks like a leaked prompt or instruction."""
    if not text:
        return fallback
    # Detect 3rd-person instruction patterns that shouldn't face the user
    leak_markers = (
        "l'utilisateur",
        "the user",
        "genere ",
        "génère ",
        "transforme ",
        "reponds en json",
        "réponds en json",
        "session_note",
        "session_title",
    )
    lower = text.lower()
    if any(marker in lower for marker in leak_markers):
        logger.warning("Prompt leak detected in LLM output, using fallback: %s", text[:80])
        return fallback
    return text


def _merge_week_enrichment(planner_output: dict, enrichment: dict) -> dict:
    base_days = planner_output["days"]
    enriched_days = enrichment.get("days", [])
    by_day = {day["day"]: day for day in enriched_days if isinstance(day, dict) and day.get("day")}

    merged_days = []
    for day in base_days:
        payload = by_day.get(day["day"], {})
        watch_title = payload.get("watch_title")
        watch_detail = payload.get("watch_detail")
        # Enrich title and goal only if LLM provided more specific versions
        enriched_title = str(payload.get("session_title") or "").strip()
        enriched_goal = str(payload.get("session_goal") or "").strip()
        enriched_description = str(payload.get("session_description") or "").strip()
        raw_note = str(payload.get("session_note") or day["session_note"]).strip()
        merged_days.append(
            {
                **day,
                "session_title": enriched_title if enriched_title else day["session_title"],
                "session_goal": enriched_goal if enriched_goal else day["session_goal"],
                "session_note": _sanitize_coach_text(raw_note, day["session_note"]),
                "session_description": _sanitize_coach_text(enriched_description, day.get("session_description", "")) if enriched_description else day.get("session_description", ""),
                "watch_items": [
                    (
                        str(watch_title).strip() if watch_title else day["watch_items"][0][0],
                        str(watch_detail).strip() if watch_detail else day["watch_items"][0][1],
                    )
                ],
            }
        )

    return {
        "intention": str(enrichment.get("intention") or planner_output["intention_seed"]).strip(),
        "summary": str(enrichment.get("summary") or planner_output["intention_seed"]).strip(),
        "days": merged_days,
    }


def _fallback_voice_preview(context: dict) -> list[str]:
    coach = build_coach_profile(context)
    coach_name = coach["coach_name"]
    return [
        f"{coach_name} est la. Mardi a l'air fragile. Je prefere garder de l'air plutot que forcer un faux bloc.",
        f"Je te construis une semaine tenable. Si mardi bouge, je garde la structure et je deplace intelligemment.",
        f"Je veux une semaine qui te ressemble, pas une semaine parfaite sur le papier. On pose les bons reperes et on garde du jeu.",
    ]


def _fallback_recap(context: dict) -> str:
    coach = build_coach_profile(context)
    sports = ", ".join(context["sports"])
    constraints = ", ".join(context["constraints"][:3]) or "pas de contrainte forte explicite"
    goal_summary = build_goal_summary(context) or context["primary_objective"]
    current_state = context.get("current_state_notes") or "forme recente encore a affiner"
    return (
        f"Voila ce que j'ai retenu pour commencer.\n"
        f"Tu veux avancer sur {goal_summary} avec une semaine ou {sports} doivent cohabiter proprement.\n"
        f"Etat de depart retenu: {current_state}.\n"
        f"Je garde en tete: {constraints}.\n"
        f"Je protegerai d'abord les creneaux tenables et les seances qui comptent vraiment.\n"
        f"Le coach va parler en mode {coach['coach_preset_label'].lower()}, avec une voix {coach['coach_soul']}, et il evitera {coach['coach_dont'] or 'les phrases vides'}."
    )


def _fallback_week_plan(planner_output: dict, coach_profile: dict) -> dict:
    days = []
    for day in planner_output["days"]:
        days.append(
            {
                **day,
                "session_note": _fallback_day_note(day, coach_profile),
                "session_description": day.get("session_description", ""),
                "watch_items": day["watch_items"],
            }
        )

    return {
        "intention": planner_output["intention_seed"],
        "summary": _fallback_summary(days, coach_profile["coach_name"]),
        "days": days,
    }


def _fallback_day_note(day: dict, coach_profile: dict) -> str:
    coach_name = coach_profile["coach_name"]
    if day["sport_type"] == "rest":
        return f"{coach_name} laisse de l'air ici. Mieux vaut garder de la marge que remplir pour rien."
    if day["priority"] == "Seance cle":
        return f"{coach_name} pose ce bloc ici parce qu'il doit compter sans casser le reste."
    if day["priority"] == "Repere fort":
        return f"{coach_name} garde ce repere pour lire si la semaine tient vraiment dans la vraie vie."
    return f"{coach_name} garde cette seance lisible et utile. Le but est d'empiler proprement, pas de rajouter du bruit."


def _fallback_summary(days: list[dict], coach_name: str) -> str:
    active = [day for day in days if day["sport_type"] != "rest"]
    sports = ", ".join(sorted({day["sport_type"] for day in active}))
    return f"{coach_name} pose une semaine claire entre {sports}, avec un bloc fort, un repere long, et assez d'air pour que ca reste vivable."


def extract_facts(user_text: str, assistant_text: str, existing_facts: list[dict]) -> list[dict]:
    prompt = f"""Analyse cet echange et decide s'il faut memoriser des faits utiles pour le coach.

Faits deja connus:
{json.dumps(existing_facts, ensure_ascii=False)}

Utilisateur:
{user_text}

Coach:
{assistant_text}

Tu dois extraire seulement des faits:
- stables
- personnels
- actionnables
- utiles pour les prochaines decisions

Ne memorise PAS:
- humeur passagere
- phrase vague
- details jetables
- diagnostics

Pour chaque fait, evalue sa duree de vie selon la categorie:
- Une douleur/blessure/gene = category "health", persiste plusieurs semaines
- Une fatigue passagere = category "fatigue", dure 1-2 jours seulement
- Une indispo ponctuelle = category "availability", dure 1-3 jours
- Un objectif ou preference = category "goal"/"preference", persiste longtemps
- Un claim d'activite = category "execution", ne persiste que la journee
Ne confonds pas une blessure (long terme, affecte le plan) avec une fatigue (court terme, signal du jour).

IMPORTANT: Si un fait existant couvre deja le meme sujet (meme category + meme key ou sujet proche), utilise le MEME key avec action "upsert" pour le mettre a jour. Ne cree PAS de nouveau fait avec un key different pour le meme sujet.

Retourne un JSON: {{"facts": [...]}}

Chaque fact:
- category: "preference" | "constraint" | "pattern" | "coaching" | "fatigue" | "availability" | "health" | "goal" | "objective" | "execution"
- key: slug court (reutilise le key existant si c'est une mise a jour)
- value: phrase courte utile
- confidence: float 0..1
- confirmed: bool
- source: "conversation"
- action: "upsert" | "archive"

Si rien d'utile: {{"facts": []}}"""

    data = _request_json(system=_COACH_SOUL, prompt=prompt, max_tokens=900)
    if data and isinstance(data.get("facts"), list):
        return [_normalize_fact_payload(fact) for fact in data["facts"] if isinstance(fact, dict)]
    return []


def select_prompt_facts(facts: list[dict]) -> list[str]:
    return select_relevant_facts([normalize_fact_memory_payload(fact) for fact in facts], affects=["conversation"], limit=6)


def _normalize_fact_payload(fact: dict) -> dict:
    value = str(fact.get("value", "")).strip()
    key = str(fact.get("key") or _slugify(value[:48])).strip() or "fact"
    category = str(fact.get("category", "preference")).strip() or "preference"
    action = str(fact.get("action", "upsert")).strip() or "upsert"
    normalized = {
        "category": category,
        "key": key,
        "value": value,
        "confidence": float(fact.get("confidence", 0.7)),
        "confirmed": bool(fact.get("confirmed", False)),
        "source": str(fact.get("source", "conversation")).strip() or "conversation",
        "action": action,
        "active": action != "archive",
    }
    return normalize_fact_memory_payload(normalized)


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:120] or "fact"
