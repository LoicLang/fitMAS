"""Legacy CoachDecision provider compatibility only.

Do not add new conversation runtime authority here.

The active Decision Runtime should route user-facing conversation lanes through
canonical Understanding, planning, command, and reply bridges before this module.
This file stays temporarily for package compatibility and old provider helpers.
"""

from __future__ import annotations

import logging
from typing import Any

from . import (
    gateway as gw,
    legacy_action_compile,
    legacy_fact_memory,
    legacy_parser,
    legacy_prompt,
    legacy_provider,
    legacy_schema_repair,
    legacy_tool_loop,
)
from fitmas.legacy.decision_contracts import CoachDecision, MutationDecision
from fitmas.prompt_observability import DecideFailureReason, PromptTrace
from fitmas.tools.contract import ToolContext
from fitmas.tools.metrics import log_tool_trace
from fitmas.tools.runtime import ToolExecution, execute_tool_calls

logger = logging.getLogger("fitmas.llm")

_normalize_day = legacy_parser.normalize_day
_parse_llm_decision_payload = legacy_parser.parse_llm_decision_payload
_validate_decision_payload = legacy_parser.validate_decision_payload
parse_coach_decision_payload = legacy_parser.parse_coach_decision_payload
_parse_nested_mutation_decision = legacy_parser.parse_nested_mutation_decision
_parse_nested_plan_patch = legacy_parser.parse_nested_plan_patch
_unwrap_plan_patch_payload = legacy_parser.unwrap_plan_patch_payload
_normalize_plan_patch_payload = legacy_parser.normalize_plan_patch_payload
_normalize_plan_patch_operation = legacy_parser.normalize_plan_patch_operation
_valid_coach_message = legacy_parser.valid_coach_message
_optional_str = legacy_parser.optional_str
_optional_int = legacy_parser.optional_int
_normalize_pending_resolution = legacy_parser.normalize_pending_resolution
_build_coach_decision_from_payload = legacy_parser.build_coach_decision_from_payload
_normalize_memory_actions = legacy_parser.normalize_memory_actions
_has_unknown_memory_action = legacy_parser.has_unknown_memory_action
_normalize_execution_actions = legacy_parser.normalize_execution_actions
_has_unknown_execution_action = legacy_parser.has_unknown_execution_action
_normalize_execution_status = legacy_parser.normalize_execution_status
_message_claims_execution_receipt_without_action = legacy_parser.message_claims_execution_receipt_without_action
_repair_execution_receipt_without_action_decision = legacy_parser.repair_execution_receipt_without_action_decision
_normalize_bool = legacy_parser.normalize_bool
_normalize_confidence = legacy_parser.normalize_confidence
_missing_create_session_fields = legacy_parser.missing_create_session_fields
_message_claims_plan_action_without_mutation = legacy_parser.message_claims_plan_action_without_mutation
_looks_truncated_fitmas_message = legacy_parser.looks_truncated_fitmas_message
_remember_invalid_decision = legacy_parser.remember_invalid_decision
_downgrade_free_confirmation_payload = legacy_parser.downgrade_free_confirmation_payload

def _client():
    return legacy_provider.client()


def _request_text(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 512) -> str | None:
    """Request text — routes through module-level _request_message (patchable by tests)."""
    return legacy_provider.request_text(
        system=system,
        prompt=prompt,
        model=model,
        max_tokens=max_tokens,
        request_message_fn=_request_message,
    )


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
    return legacy_provider.request_message(
        system=system,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        thinking=thinking,
        output_config=output_config,
    )


def _request_json(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 1024) -> dict | None:
    """Request JSON — routes through module-level _request_text (patchable chain).

    Delegates parsing to llm_gateway._robust_json_loads so every JSON
    entry point (this, gw.request_json, gw.message_json) shares one
    truncation/noise-repair strategy."""
    return legacy_provider.request_json(
        system=system,
        prompt=prompt,
        model=model,
        max_tokens=max_tokens,
        request_text_fn=_request_text,
    )


def _request_structured_json(
    *,
    system: str,
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 1024,
    schema_hint: str | None = None,
) -> dict | None:
    """Request structured JSON through the gateway, preserving test patchability.

    In local/unit contexts without DeepSeek configured, keep the old Anthropic
    path so existing tests can patch `_request_message`. With DeepSeek, use the
    gateway's structured-output path and provider fallback.
    """
    return legacy_provider.request_structured_json(
        system=system,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        schema_hint=schema_hint,
        request_json_fn=_request_json,
        default_request_json_fn=_DEFAULT_REQUEST_JSON,
        request_message_fn=_request_message,
        default_request_message_fn=_DEFAULT_REQUEST_MESSAGE,
        request_text_fn=_request_text,
        gateway_request_structured_json_fn=gw.request_structured_json,
        default_gateway_structured_json_fn=_DEFAULT_GATEWAY_STRUCTURED_JSON,
    )


_DEFAULT_REQUEST_MESSAGE = _request_message
_DEFAULT_REQUEST_JSON = _request_json
_DEFAULT_GATEWAY_STRUCTURED_JSON = gw.request_structured_json
_LAST_DECIDE_NONE: dict[str, Any] | None = None
_DECIDE_FAILURE_EVENTS: list[dict[str, str]] = []


def _use_deepseek_openai_structured_output() -> bool:
    return legacy_provider.use_deepseek_openai_structured_output()


def _log_decide_none(reason: DecideFailureReason, *, prompt_trace: PromptTrace | None = None) -> None:
    global _LAST_DECIDE_NONE
    _record_decide_failure_event(reason, stage="final")
    _LAST_DECIDE_NONE = {
        "reason": reason.value,
        "prompt_trace": prompt_trace.as_dict() if prompt_trace else None,
        "events": [dict(event) for event in _DECIDE_FAILURE_EVENTS],
    }
    logger.info(
        "llm.decide_none reason=%s prompt_trace=%s",
        reason.value,
        _LAST_DECIDE_NONE["prompt_trace"],
    )


def clear_last_decide_none() -> None:
    global _LAST_DECIDE_NONE, _DECIDE_FAILURE_EVENTS
    _LAST_DECIDE_NONE = None
    _DECIDE_FAILURE_EVENTS = []


def get_last_decide_none() -> dict[str, Any] | None:
    if _LAST_DECIDE_NONE is None:
        return None
    payload = dict(_LAST_DECIDE_NONE)
    payload["events"] = [dict(event) for event in payload.get("events", [])]
    return payload


def _record_decide_failure_event(reason: DecideFailureReason, *, stage: str) -> None:
    event = {"reason": reason.value, "stage": stage}
    if _DECIDE_FAILURE_EVENTS and _DECIDE_FAILURE_EVENTS[-1] == event:
        return
    _DECIDE_FAILURE_EVENTS.append(event)


def _render_prompt_trace_tuple(values: tuple[str, ...]) -> str:
    return ",".join(values) if values else "none"


def _log_decide_prompt_trace(prompt_trace: PromptTrace | None, *, tool_names: tuple[str, ...]) -> None:
    if prompt_trace is None:
        return
    rendered_tool_names = tool_names or prompt_trace.tool_names
    logger.info(
        "llm.decide_prompt_trace route=%s intent=%s provider=%s model=%s prompt_policy=%s "
        "prompt_contract=%s tools=%s truth_blocks=%s system_chars=%s user_chars=%s "
        "total_chars=%s history_messages_used=%s",
        prompt_trace.route,
        prompt_trace.intent,
        prompt_trace.provider,
        prompt_trace.model,
        prompt_trace.prompt_policy,
        prompt_trace.prompt_contract,
        _render_prompt_trace_tuple(rendered_tool_names),
        _render_prompt_trace_tuple(prompt_trace.truth_block_names),
        prompt_trace.system_chars,
        prompt_trace.user_chars,
        prompt_trace.total_chars,
        prompt_trace.history_messages_used,
    )


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

    prompt_bundle = legacy_prompt.build_legacy_decision_prompt(
        user_text=user_text,
        timeline_summary=timeline_summary,
        execution_summary=execution_summary,
        temporal_summary=temporal_summary,
        activity_claim_summary=activity_claim_summary,
        signal_summary=signal_summary,
        conversation_history=conversation_history,
        coach_context=coach_context,
        remembered_facts=remembered_facts,
        time_context=time_context,
        tool_context=tool_context,
        select_prompt_facts_fn=legacy_fact_memory.select_prompt_facts,
    )
    prompt = prompt_bundle.prompt
    history_messages_used = prompt_bundle.history_messages_used
    system_prompt = prompt_bundle.system_prompt
    prompt_trace = prompt_bundle.prompt_trace
    prompt_policy = prompt_bundle.prompt_policy
    tool_names = prompt_bundle.tool_names
    _log_decide_prompt_trace(prompt_trace, tool_names=tool_names)

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
                _record_decide_failure_event(DecideFailureReason.TOOL_LOOP_FAILED, stage="tool_loop")
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
            _record_decide_failure_event(DecideFailureReason.SCHEMA_INVALID, stage="initial_parse")
            initial_invalid_payload = legacy_parser.get_last_invalid_decision_payload()
            data = _repair_invalid_decision_payload(data=initial_invalid_payload, system=system_prompt, prompt=prompt)
            parsed_decision = _parse_llm_decision_payload(data)
            if parsed_decision is None:
                parsed_decision = _repair_execution_receipt_without_action_decision(
                    data=legacy_parser.get_last_invalid_decision_payload() or data or initial_invalid_payload,
                    coach_context=coach_context,
                )
        if parsed_decision is None:
            _record_decide_failure_event(DecideFailureReason.REPAIR_FAILED, stage="repair")
            data = _request_claude_decision_fallback(system=system_prompt, prompt=prompt)
            parsed_decision = _parse_llm_decision_payload(data)
            if parsed_decision is None:
                parsed_decision = _repair_execution_receipt_without_action_decision(
                    data=legacy_parser.get_last_invalid_decision_payload() or data,
                    coach_context=coach_context,
                )
        if parsed_decision is None:
            _log_decide_none(DecideFailureReason.FALLBACK_FAILED, prompt_trace=prompt_trace)
            return None

        if isinstance(parsed_decision, CoachDecision):
            parsed_decision = legacy_action_compile.maybe_compile_execution_actions_for_turn(
                decision=parsed_decision,
                system=system_prompt,
                prompt=prompt,
                coach_context=coach_context,
                request_structured_json_fn=_request_structured_json,
            )
            parsed_decision = legacy_action_compile.maybe_compile_memory_actions_for_turn(
                decision=parsed_decision,
                system=system_prompt,
                prompt=prompt,
                coach_context=coach_context,
                request_structured_json_fn=_request_structured_json,
            )
            parsed_decision = legacy_action_compile.maybe_repair_missing_execution_action_from_followup(
                decision=parsed_decision,
                system=system_prompt,
                prompt=prompt,
                coach_context=coach_context,
                request_structured_json_fn=_request_structured_json,
            )
            parsed_decision = legacy_action_compile.maybe_repair_execution_action_consistency(
                decision=parsed_decision,
                system=system_prompt,
                prompt=prompt,
                coach_context=coach_context,
                request_structured_json_fn=_request_structured_json,
            )
            parsed_decision = legacy_action_compile.maybe_repair_missing_availability_memory_action(
                decision=parsed_decision,
                system=system_prompt,
                prompt=prompt,
                coach_context=coach_context,
                request_structured_json_fn=_request_structured_json,
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


def _repair_invalid_decision_payload(*, data: dict[str, Any] | None, system: str, prompt: str) -> dict | None:
    """Retry once with the invalid payload and the FitMAS decision contract."""
    return legacy_schema_repair.repair_invalid_decision_payload(
        data=data,
        system=system,
        prompt=prompt,
        request_structured_json_fn=_request_structured_json,
        downgrade_free_confirmation_fn=_downgrade_free_confirmation_payload,
    )


def _request_claude_decision_fallback(*, system: str, prompt: str) -> dict | None:
    """Use Claude as a schema fallback after a structured DeepSeek payload failed validation."""
    return legacy_schema_repair.request_claude_decision_fallback(
        system=system,
        prompt=prompt,
        gateway_request_structured_json_fn=gw.request_structured_json,
        downgrade_free_confirmation_fn=_downgrade_free_confirmation_payload,
    )


def _classify_llm_exception(exc: BaseException) -> str:
    """Classify a raised exception so operators can triage failures.

    Returns a short stable label (`timeout`, `rate_limit`, `bad_request`,
    `auth`, `connection`, `api_other`, `json_parse`, `unknown`). The
    labels are log-only — `decide()` still returns None for every case.
    """
    return legacy_provider.classify_llm_exception(exc)


def _deepseek_tool_thinking_kwargs() -> dict[str, dict[str, str]]:
    return legacy_provider.deepseek_tool_thinking_kwargs()


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
    return legacy_tool_loop.request_json_with_tools(
        system=system,
        prompt=prompt,
        tool_context=tool_context,
        tool_names=tool_names,
        context_policy=context_policy,
        history_messages_used=history_messages_used,
        model=model,
        max_tokens=max_tokens,
        dependencies=legacy_tool_loop.LegacyToolLoopDependencies(
            request_message_fn=_request_message,
            request_structured_json_fn=_request_structured_json,
            execute_tool_calls_fn=execute_tool_calls,
            log_tool_trace_fn=log_tool_trace,
            tool_thinking_kwargs_fn=_deepseek_tool_thinking_kwargs,
        ),
    )

def _repair_decision_json_from_text(
    raw_text: str | None,
    *,
    model: str = "claude-haiku-4-5-20251001",
    context_prompt: str | None = None,
    tool_result_summary: str | None = None,
) -> dict | None:
    """Convert a prose decision-like answer into canonical JSON once."""
    return legacy_schema_repair.repair_decision_json_from_text(
        raw_text,
        model=model,
        context_prompt=context_prompt,
        tool_result_summary=tool_result_summary,
        request_structured_json_fn=_request_structured_json,
        downgrade_free_confirmation_fn=_downgrade_free_confirmation_payload,
    )


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
    repaired["fitmas_message"] = "Signal pris. Je reste prudent et je ne touche pas au plan sans adaptation valide."
    return repaired


def _repair_tool_result_summary(
    tool_executions: list[ToolExecution],
    *,
    payload_char_limit: int = 2500,
) -> str | None:
    return legacy_schema_repair.repair_tool_result_summary(
        tool_executions,
        payload_char_limit=payload_char_limit,
    )


def _looks_like_provider_tool_markup(raw_text: str) -> bool:
    return legacy_schema_repair.looks_like_provider_tool_markup(raw_text)
