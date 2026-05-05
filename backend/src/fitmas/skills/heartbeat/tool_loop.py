"""Read-tool loop for proactive heartbeat generation."""
from __future__ import annotations

import json
import os
from typing import Any

from fitmas import llm_gateway as gw
from fitmas.llm_gateway import generate_heartbeat_text_with_debug
from fitmas.tools.contract import ToolCall, ToolContext
from fitmas.tools.registry import list_tools_for_pipeline
from fitmas.tools.runtime import ToolExecution, execute_tool_calls


HEARTBEAT_TOOL_NAMES: tuple[str, ...] = (
    "get_plan_window",
    "get_recent_activities",
    "get_activity_highlights",
    "get_recent_reality_window",
    "get_load_context",
    "get_user_constraints",
    "get_relevant_facts",
    "suggest_replan_candidates",
    "validate_plan_patch",
    "validate_week_coherence",
)
HEARTBEAT_READ_TOOL_NAMES = HEARTBEAT_TOOL_NAMES
MAX_HEARTBEAT_TOOL_ROUNDS = 2
MAX_HEARTBEAT_TOOL_CALLS = 4


def heartbeat_read_tools_enabled(tool_context: ToolContext | None) -> bool:
    if tool_context is None:
        return False
    raw = str(os.getenv("FITMAS_ENABLE_HEARTBEAT_READ_TOOLS", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def generate_heartbeat_text_with_tools_debug(
    system: str,
    prompt: str,
    *,
    allow_no_send: bool,
    tool_context: ToolContext | None,
) -> dict[str, Any]:
    if tool_context is None:
        generation = generate_heartbeat_text_with_debug(system, prompt, allow_no_send=allow_no_send)
        return {
            "raw_text": generation.raw_text,
            "text": generation.text,
            "reason": generation.reason,
            "allow_no_send": generation.allow_no_send,
            "tools": {},
        }
    tools = list_tools_for_pipeline(tool_context.pipeline, tool_names=HEARTBEAT_TOOL_NAMES)
    tool_names = [str(tool.get("name") or "") for tool in tools]
    if not tools:
        generation = generate_heartbeat_text_with_debug(system, prompt, allow_no_send=allow_no_send)
        return {
            "raw_text": generation.raw_text,
            "text": generation.text,
            "reason": generation.reason,
            "allow_no_send": generation.allow_no_send,
            "tools": {"offered": [], "requested": [], "results": []},
        }

    final_system = (
        f"{system}\n\n"
        "Tu as acces a des tools heartbeat bornes. Les read-tools lisent le plan, "
        "les activites, les contraintes, la memoire et la charge. "
        "`suggest_replan_candidates`, `validate_plan_patch` et `validate_week_coherence` peuvent aider a proposer un ajustement, "
        "mais aucun tool heartbeat ne commit en base. "
        "Utilise les tools avant une affirmation factuelle fragile. "
        "Si tu proposes un changement de planning, appelle `validate_plan_patch` puis `validate_week_coherence` avant ta reponse finale "
        "et formule uniquement une demande de confirmation."
    )
    if allow_no_send:
        final_system += gw.NO_SEND_INSTRUCTION

    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    response = gw.request_message(
        system=final_system,
        messages=messages,
        model=gw.DEFAULT_FAST_MODEL,
        max_tokens=256,
        tools=tools,
        tool_choice={"type": "auto"},
    )
    if response is None:
        return _generation(
            raw_text=None,
            text=None,
            reason="llm_unavailable",
            allow_no_send=allow_no_send,
            tools={"offered": tool_names, "requested": [], "results": []},
        )

    tool_rounds = 0
    tool_calls_used = 0
    requested: list[str] = []
    results_debug: list[dict[str, Any]] = []
    candidate_plan_patch: dict[str, Any] | None = None
    while True:
        stop_reason = str(getattr(response, "stop_reason", "") or "")
        if stop_reason != "tool_use":
            normalized = _normalize_heartbeat_generation(
                gw.message_text(response),
                allow_no_send=allow_no_send,
            )
            normalized["tools"] = {"offered": tool_names, "requested": requested, "results": results_debug}
            if candidate_plan_patch is not None:
                normalized["candidate_plan_patch"] = candidate_plan_patch
            return normalized

        tool_blocks = _tool_use_blocks(response)
        if not tool_blocks:
            normalized = _normalize_heartbeat_generation(
                gw.message_text(response),
                allow_no_send=allow_no_send,
            )
            normalized["reason"] = "tool_use_without_blocks"
            normalized["tools"] = {"offered": tool_names, "requested": requested, "results": results_debug}
            return normalized

        tool_rounds += 1
        remaining_budget = max(0, MAX_HEARTBEAT_TOOL_CALLS - tool_calls_used)
        tool_calls = [
            ToolCall(tool_name=str(getattr(block, "name", "")), arguments=dict(getattr(block, "input", {}) or {}))
            for block in tool_blocks
        ]
        requested.extend(call.tool_name for call in tool_calls)
        executions = execute_tool_calls(
            tool_calls,
            context=tool_context,
            max_tools=remaining_budget,
            llm_round_trips=tool_rounds + 1,
        )
        candidate_plan_patch = _candidate_plan_patch_from_tools(tool_calls, executions) or candidate_plan_patch
        tool_calls_used += min(len(tool_calls), remaining_budget)
        results_debug.extend(_tool_results_debug(executions))
        messages.append({"role": "assistant", "content": gw.serialize_content_blocks(getattr(response, "content", []))})
        allow_more_tools = tool_rounds < MAX_HEARTBEAT_TOOL_ROUNDS and tool_calls_used < MAX_HEARTBEAT_TOOL_CALLS
        messages.append(
            {
                "role": "user",
                "content": _tool_followup_content(
                    tool_blocks,
                    executions,
                    allow_more_tools=allow_more_tools,
                ),
            }
        )
        response = gw.request_message(
            system=final_system,
            messages=messages,
            model=gw.DEFAULT_FAST_MODEL,
            max_tokens=256,
            tools=tools if allow_more_tools else None,
            tool_choice={"type": "auto"} if allow_more_tools else None,
        )
        if response is None:
            return _generation(
                raw_text=None,
                text=None,
                reason="tool_followup_unavailable",
                allow_no_send=allow_no_send,
                tools={"offered": tool_names, "requested": requested, "results": results_debug},
            )


def _tool_use_blocks(response: Any) -> list[Any]:
    return [
        block
        for block in (getattr(response, "content", []) or [])
        if getattr(block, "type", None) == "tool_use"
    ]


def _tool_followup_content(
    tool_use_blocks: list[Any],
    executions: list[ToolExecution],
    *,
    allow_more_tools: bool,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for tool_use_block, execution in zip(tool_use_blocks, executions):
        result = execution.result
        content.append(
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
    if allow_more_tools:
        text = (
            "Tu peux appeler un autre tool si une information manque. "
            "Si tu proposes un changement, valide-le d'abord avec validate_plan_patch puis validate_week_coherence. "
            "Sinon reponds en prose coach courte, ou NO_SEND si rien d'utile."
        )
    else:
        text = (
            "Budget tools termine. Reponds maintenant en prose coach courte, "
            "demande confirmation si un PlanPatch vient d'etre valide, ou NO_SEND si rien d'utile."
        )
    content.append({"type": "text", "text": text})
    return content


def _tool_results_debug(executions: list[ToolExecution]) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": execution.result.tool_name,
            "status": execution.result.status,
            "summary": execution.result.summary,
            "error": execution.result.error,
            "payload": execution.result.payload,
        }
        for execution in executions
    ]


def _candidate_plan_patch_from_tools(
    tool_calls: list[ToolCall],
    executions: list[ToolExecution],
) -> dict[str, Any] | None:
    for call, execution in zip(tool_calls, executions):
        if call.tool_name not in {"validate_plan_patch", "validate_week_coherence"}:
            continue
        raw_patch = call.arguments.get("patch")
        if not isinstance(raw_patch, dict):
            continue
        result = execution.result
        if result.status != "ok" or not isinstance(result.payload, dict):
            continue
        validation = _candidate_validation_payload(call.tool_name, result.payload)
        validation_status = str(validation.get("status") or "").strip()
        if validation_status not in {"valid", "warning", "requires_confirmation"}:
            continue
        candidate = {
            "patch": raw_patch,
            "validation": validation,
            "summary": result.summary,
        }
        if call.tool_name == "validate_week_coherence":
            review = result.payload.get("review")
            if not isinstance(review, dict):
                continue
            review_status = str(review.get("status") or "").strip()
            if review_status not in {"valid", "warning", "requires_confirmation"}:
                continue
            candidate["week_review"] = review
        return candidate
    return None


def _candidate_validation_payload(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "validate_week_coherence":
        validation = payload.get("validation")
        return validation if isinstance(validation, dict) else {}
    return payload


def _normalize_heartbeat_generation(raw_text: str | None, *, allow_no_send: bool) -> dict[str, Any]:
    if not raw_text:
        return _generation(raw_text=None, text=None, reason="empty_response", allow_no_send=allow_no_send)
    text = str(raw_text).strip()
    cleaned = text.replace("*", "").replace("`", "").replace("#", "").strip()
    if allow_no_send and cleaned.upper() == gw.NO_SEND_TOKEN:
        return _generation(raw_text=raw_text, text=None, reason="no_send_token", allow_no_send=allow_no_send)
    if allow_no_send and gw.NO_SEND_TOKEN in text.upper() and len(text) < 100:
        return _generation(raw_text=raw_text, text=None, reason="no_send_short_ack", allow_no_send=allow_no_send)
    if allow_no_send and gw.NO_SEND_TOKEN in text.upper():
        text = text.replace(gw.NO_SEND_TOKEN, "").replace("no_send", "").strip()
        if not text:
            return _generation(raw_text=raw_text, text=None, reason="no_send_after_strip", allow_no_send=allow_no_send)
    return _generation(raw_text=raw_text, text=text, reason="generated", allow_no_send=allow_no_send)


def _generation(
    *,
    raw_text: str | None,
    text: str | None,
    reason: str,
    allow_no_send: bool,
    tools: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "raw_text": raw_text,
        "text": text,
        "reason": reason,
        "allow_no_send": allow_no_send,
    }
    if tools is not None:
        payload["tools"] = tools
    return payload
