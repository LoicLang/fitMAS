from __future__ import annotations

import json
from typing import Any

from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import LLMClient, LLMResponse, ToolCall, ToolSchema
from fitmas.runtime_v0.proposals import ActionProposal
from fitmas.runtime_v0.snapshot import SnapshotHeader
from fitmas.runtime_v0.tools_read import ToolContext

ANSWER_SUPPORT_TOOLS = {"get_current_plan", "get_plan_day", "get_session", "get_recent_execution_events"}
class CoachAgent:
    def __init__(self, llm_client: LLMClient, system_prompt: str):
        self.llm_client = llm_client
        self.system_prompt = system_prompt

    def run(
        self,
        event: InputEvent,
        snapshot_header: SnapshotHeader,
        tools: tuple[ToolSchema, ...] | list[ToolSchema],
        max_steps: int = 3,
        tool_context: ToolContext | None = None,
    ) -> ActionProposal:
        tool_by_name = {tool.name: tool for tool in tools}
        messages = _initial_messages(event, snapshot_header)
        read_facts: list[str] = []
        read_tool_names: list[str] = []
        unknown_tool_retry_used = False
        invalid_args_retry_used = False
        answer_support_retry_used = False
        plan_patch_support_retry_used = False
        active_intent_retry_used = False
        date_resolution_retry_used = False

        for _ in range(max_steps):
            response = self.llm_client.chat_with_tools(self.system_prompt, messages, list(tools))
            proposal: ActionProposal | None = None
            error_call: ToolCall | None = None
            error_reason: str | None = None
            if response.tool_calls and _has_read_tool_call(response, tool_by_name):
                error_call, error_reason = _execute_read_tool_calls(
                    response,
                    tool_by_name,
                    tool_context,
                    messages,
                    read_facts,
                    read_tool_names,
                )
                if error_reason:
                    if error_reason == "unknown_tool":
                        if unknown_tool_retry_used:
                            return _no_send("unknown_tool", tool_context)
                        unknown_tool_retry_used = True
                    else:
                        if invalid_args_retry_used:
                            return _no_send("invalid_tool_args", tool_context)
                        invalid_args_retry_used = True
                    continue
                proposal, error_call, error_reason = _first_proposal(response, tool_by_name, tool_context)
            else:
                proposal, error_call, error_reason = _first_proposal(response, tool_by_name, tool_context)
            if error_reason:
                messages.append(_tool_error(error_call, f"invalid_tool_args: {error_reason}"))
                if invalid_args_retry_used:
                    return _no_send("invalid_tool_args", tool_context)
                invalid_args_retry_used = True
                continue
            if proposal is not None:
                if _active_move_intent(snapshot_header.last_unresolved_intent) and proposal.type == "execution_update":
                    messages.append(_runtime_contract_error("active_move_intent_requires_plan_patch"))
                    if active_intent_retry_used:
                        return _no_send("active_move_intent_requires_plan_patch", tool_context)
                    active_intent_retry_used = True
                    continue
                if _plan_patch_needs_source_retry(proposal, snapshot_header):
                    messages.append(_runtime_contract_error("plan_patch_source_not_anchored"))
                    if plan_patch_support_retry_used:
                        return _no_send("plan_patch_source_not_anchored", tool_context)
                    plan_patch_support_retry_used = True
                    continue
                if _planning_date_needs_resolution_retry(proposal, snapshot_header):
                    messages.append(_runtime_contract_error("planning_date_not_resolved"))
                    if date_resolution_retry_used:
                        return _no_send("planning_date_not_resolved", tool_context)
                    date_resolution_retry_used = True
                    continue
                return proposal
            if response.tool_calls:
                unknown_call = next((call for call in response.tool_calls if call.name not in tool_by_name), None)
                if unknown_call is not None:
                    messages.append(_tool_error(unknown_call, "unknown_tool"))
                    if unknown_tool_retry_used:
                        return _no_send("unknown_tool", tool_context)
                    unknown_tool_retry_used = True
                continue
            if response.text:
                if _active_move_intent(snapshot_header.last_unresolved_intent):
                    messages.append(_runtime_contract_error("active_move_intent_requires_plan_patch"))
                    if active_intent_retry_used:
                        return _no_send("active_move_intent_requires_plan_patch", tool_context)
                    active_intent_retry_used = True
                    continue
                if not read_facts:
                    return _no_send("missing_read_support", tool_context)
                if not _has_answer_support(read_tool_names, tool_by_name):
                    reason = "planning_date_resolution_requires_proposal" if "resolve_date_reference" in read_tool_names else "missing_answer_read_support"
                    messages.append(_runtime_contract_error(reason))
                    if answer_support_retry_used:
                        return _no_send(reason, tool_context)
                    answer_support_retry_used = True
                    continue
                return ActionProposal(
                    type="answer",
                    confidence=0.8,
                    user_intent_summary="answer_from_read_tools",
                    evidence=tuple(read_facts),
                    answer_facts=tuple(read_facts),
                    tool_trace=_trace(tool_context),
                )
        return _no_send("max_steps_reached", tool_context)
def _initial_messages(event: InputEvent, snapshot_header: SnapshotHeader) -> list[dict[str, Any]]:
    return [
        {"role": "system_context", "content": snapshot_header.to_prompt_text()},
        {"role": "user", "content": event.text or ""},
    ]
def _first_proposal(
    response: LLMResponse,
    tool_by_name: dict[str, ToolSchema],
    tool_context: ToolContext | None,
) -> tuple[ActionProposal | None, ToolCall | None, str | None]:
    for call in response.tool_calls:
        tool = tool_by_name.get(call.name)
        if tool is None or not tool.is_proposal:
            continue
        try:
            proposal = _call_tool(tool, call.args, tool_context)
        except Exception as exc:
            return None, call, str(exc)
        if isinstance(proposal, ActionProposal):
            return proposal, None, None
        return None, call, f"proposal_tool_returned_{type(proposal).__name__}"
    return None, None, None

def _has_read_tool_call(response: LLMResponse, tool_by_name: dict[str, ToolSchema]) -> bool:
    return any(
        (tool := tool_by_name.get(call.name)) is not None and not tool.is_proposal
        for call in response.tool_calls
    )

def _execute_read_tool_calls(
    response: LLMResponse,
    tool_by_name: dict[str, ToolSchema],
    tool_context: ToolContext | None,
    messages: list[dict[str, Any]],
    read_facts: list[str],
    read_tool_names: list[str],
) -> tuple[ToolCall | None, str | None]:
    for call in response.tool_calls:
        tool = tool_by_name.get(call.name)
        if tool is None:
            messages.append(_tool_error(call, "unknown_tool"))
            return call, "unknown_tool"
        if tool.is_proposal:
            continue
        try:
            result = _call_tool(tool, call.args, tool_context)
        except Exception as exc:
            messages.append(_tool_error(call, f"invalid_tool_args: {exc}"))
            return call, "invalid_tool_args"
        fact = json.dumps(result, ensure_ascii=False, sort_keys=True)
        read_facts.append(fact)
        read_tool_names.append(call.name)
        messages.append({"role": "tool", "tool_name": call.name, "content": fact})
    return None, None
def _call_tool(tool: ToolSchema, args: dict[str, Any], tool_context: ToolContext | None) -> Any:
    if tool_context is None:
        return tool.handler(**args)
    return tool.handler(tool_context, **args)
def _tool_error(call: ToolCall, reason: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_name": call.name,
        "content": json.dumps({"error": reason}, ensure_ascii=False),
    }
def _runtime_contract_error(reason: str) -> dict[str, Any]:
    payload = {
        "error": reason,
        "required": sorted(ANSWER_SUPPORT_TOOLS),
        "plan_patch_rule": "call get_session for the exact source session or ask_clarification with target_date",
        "date_rule": "after resolve_date_reference, call ask_clarification or propose_plan_patch; do not answer directly",
    }
    return {
        "role": "tool",
        "tool_name": "runtime_contract",
        "content": json.dumps(payload, ensure_ascii=False),
    }

def _has_answer_support(read_tool_names: list[str], tool_by_name: dict[str, ToolSchema]) -> bool:
    if not any(name in tool_by_name for name in ANSWER_SUPPORT_TOOLS):
        return bool(read_tool_names)
    return bool(ANSWER_SUPPORT_TOOLS & set(read_tool_names))
def _plan_patch_needs_source_retry(proposal: ActionProposal, snapshot_header: SnapshotHeader) -> bool:
    if proposal.type != "plan_patch" or proposal.plan_patch is None:
        return False
    if _active_move_intent(snapshot_header.last_unresolved_intent):
        return False
    ok_tools = {item.get("name") for item in proposal.tool_trace if item.get("ok", True)}
    return "get_session" not in ok_tools
def _planning_date_needs_resolution_retry(proposal: ActionProposal, snapshot_header: SnapshotHeader) -> bool:
    target_dates = _proposal_target_dates(proposal)
    if not target_dates:
        return False
    active_target = _active_move_target(snapshot_header.last_unresolved_intent)
    if active_target is not None and all(target == active_target for target in target_dates):
        return False
    ok_tools = {item.get("name") for item in proposal.tool_trace if item.get("ok", True)}
    return "resolve_date_reference" not in ok_tools
def _proposal_target_dates(proposal: ActionProposal) -> tuple[str, ...]:
    if proposal.type == "ask_clarification" and proposal.unresolved_intent:
        target = proposal.unresolved_intent.get("target_date")
        return (target,) if isinstance(target, str) else ()
    if proposal.type == "plan_patch" and proposal.plan_patch:
        return tuple(op.target_date.isoformat() for op in proposal.plan_patch.operations if op.target_date)
    return ()

def _active_move_intent(intent: dict[str, Any] | None) -> bool:
    return intent is not None and intent.get("type") == "move_session"

def _active_move_target(intent: dict[str, Any] | None) -> str | None:
    if not _active_move_intent(intent):
        return None
    target = intent.get("target_date")
    return target if isinstance(target, str) else None

def _trace(tool_context: ToolContext | None) -> tuple[dict[str, Any], ...]:
    if tool_context is None:
        return ()
    return tuple(dict(item) for item in tool_context.scratchpad.get("calls", ()))

def _no_send(reason: str, tool_context: ToolContext | None = None) -> ActionProposal:
    return ActionProposal(type="no_send", confidence=0.0, user_intent_summary=reason, evidence=(reason,), tool_trace=_trace(tool_context))
