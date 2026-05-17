from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.llm_prompt_builder import build_layered_conversation_prompt, render_conversation_time_block
from fitmas.profile_summary import build_profile_summary
from fitmas.prompt_contracts import get_prompt_contract
from fitmas.prompt_observability import PromptTrace
from fitmas.time_context import build_time_context
from fitmas.tools.contract import ToolContext
from fitmas.tools.routing import IntentCategory

logger = logging.getLogger("fitmas.llm")

SelectPromptFacts = Callable[[list[dict]], list[str]]

_TURN_INTENT_TO_PROMPT_INTENT = {
    "close_turn": IntentCategory.CLOSE_TURN,
    "trivial_ack": IntentCategory.CASUAL_CHAT,
    "casual_chat": IntentCategory.CASUAL_CHAT,
    "needs_clarification": IntentCategory.NEEDS_CLARIFICATION,
    "calibration_answer": IntentCategory.CALIBRATION_ANSWER,
    "availability_constraint": IntentCategory.AVAILABILITY_CONSTRAINT,
    "plan_mutation": IntentCategory.PLAN_NEGOTIATION,
    "plan_lookup": IntentCategory.PLAN_LOOKUP,
    "activity_review": IntentCategory.ACTIVITY_REVIEW,
    "activity_highlights": IntentCategory.ACTIVITY_HIGHLIGHTS,
    "execution_report": IntentCategory.EXECUTION_REPORT,
    "health_signal": IntentCategory.HEALTH_SIGNAL,
    "preference_signal": IntentCategory.PLAN_NEGOTIATION,
    "generic_question": IntentCategory.GENERIC_QUESTION,
}
_CONVERSATION_TOOL_BUDGET = (
    "get_plan_window",
    "resolve_planning_window",
    "get_user_constraints",
    "validate_plan_patch",
)
_TERMINAL_NO_TOOL_INTENTS = {
    "close_turn",
    "trivial_ack",
    "casual_chat",
    "needs_clarification",
    "calibration_answer",
}


@dataclass(frozen=True, slots=True)
class LegacyDecisionPromptBundle:
    prompt: str
    system_prompt: Any
    prompt_trace: PromptTrace | None
    prompt_policy: Any
    history_messages_used: int
    tool_names: tuple[str, ...]


def build_legacy_decision_prompt(
    *,
    user_text: str,
    timeline_summary: str | None,
    execution_summary: str | None,
    temporal_summary: str | None,
    activity_claim_summary: str | None,
    signal_summary: str | None,
    conversation_history: list[dict] | None,
    coach_context: dict | None,
    remembered_facts: list[dict] | None,
    time_context: dict | None,
    tool_context: ToolContext | None,
    select_prompt_facts_fn: SelectPromptFacts,
) -> LegacyDecisionPromptBundle:
    resolved_time_context = time_context or build_time_context((coach_context or {}).get("timezone"))
    turn_prompt_intent = prompt_intent_from_turn_context(coach_context)
    prompt_policy = select_conversation_prompt_policy(
        routing_reason=None,
        intent=turn_prompt_intent,
    )
    tool_names = tool_budget_for_prompt_policy(tool_context, prompt_policy, coach_context=coach_context)
    selected_facts = (coach_context or {}).get("selected_facts") or select_prompt_facts_fn(remembered_facts or [])
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
    return LegacyDecisionPromptBundle(
        prompt=prompt_bundle.prompt,
        system_prompt=prompt_bundle.system,
        prompt_trace=prompt_bundle.trace,
        prompt_policy=prompt_policy,
        history_messages_used=prompt_bundle.history_messages_used,
        tool_names=tool_names,
    )


def prompt_intent_from_turn_context(coach_context: dict | None) -> IntentCategory | None:
    primary_intent = str((coach_context or {}).get("turn_primary_intent") or "")
    return _TURN_INTENT_TO_PROMPT_INTENT.get(primary_intent)


def is_terminal_no_tool_intent(coach_context: dict | None) -> bool:
    primary_intent = str((coach_context or {}).get("turn_primary_intent") or "")
    return primary_intent in _TERMINAL_NO_TOOL_INTENTS


def tool_budget_for_context(tool_context: ToolContext | None) -> tuple[str, ...]:
    if tool_context is None:
        return ()
    if tool_context.pipeline == "conversation":
        return _CONVERSATION_TOOL_BUDGET
    return ()


def tool_budget_for_prompt_policy(
    tool_context: ToolContext | None,
    prompt_policy: Any,
    *,
    coach_context: dict | None,
) -> tuple[str, ...]:
    if tool_context is None:
        return ()
    if is_terminal_no_tool_intent(coach_context):
        return ()
    contract_name = getattr(prompt_policy, "contract_name", None)
    if contract_name:
        try:
            return tuple(get_prompt_contract(contract_name).allowed_tools)
        except KeyError:
            logger.warning("llm.prompt_contract_missing name=%s", contract_name)
    return tool_budget_for_context(tool_context)
