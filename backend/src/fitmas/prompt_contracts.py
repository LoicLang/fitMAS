from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptContract:
    name: str
    capability: str
    allowed_tools: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    required_truth_blocks: tuple[str, ...]
    optional_truth_blocks: tuple[str, ...]
    output_schema: str
    final_reply_mode: str
    max_context_blocks: tuple[str, ...]


_PROMPT_CONTRACTS: dict[str, PromptContract] = {
    "conversation_close_turn": PromptContract(
        name="conversation_close_turn",
        capability="terminal_text",
        allowed_tools=(),
        allowed_actions=(),
        required_truth_blocks=("conversation_frame",),
        optional_truth_blocks=("temporal",),
        output_schema="final_text",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "conversation_frame"),
    ),
    "conversation_casual_chat": PromptContract(
        name="conversation_casual_chat",
        capability="terminal_text",
        allowed_tools=(),
        allowed_actions=(),
        required_truth_blocks=("conversation_frame",),
        optional_truth_blocks=("temporal",),
        output_schema="final_text",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "conversation_frame"),
    ),
    "conversation_plan_lookup": PromptContract(
        name="conversation_plan_lookup",
        capability="read_only",
        allowed_tools=("get_plan_window", "get_session_detail"),
        allowed_actions=(),
        required_truth_blocks=("temporal", "plan_window"),
        optional_truth_blocks=("execution_reality", "activity_claims"),
        output_schema="grounded_final_reply",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "planning", "execution", "conversation_frame"),
    ),
    "conversation_execution_report": PromptContract(
        name="conversation_execution_report",
        capability="write_after_validation",
        allowed_tools=("resolve_target_session", "get_recent_activities"),
        allowed_actions=("record_execution_update", "record_memory"),
        required_truth_blocks=("temporal", "execution_reality", "planning"),
        optional_truth_blocks=("activity_claims", "conversation_frame"),
        output_schema="CoachDecision",
        final_reply_mode="post_runtime",
        max_context_blocks=("temporal", "planning", "execution", "conversation_frame"),
    ),
    "conversation_plan_negotiation": PromptContract(
        name="conversation_plan_negotiation",
        capability="draft_action",
        allowed_tools=(
            "get_today_context",
            "get_plan_window",
            "get_load_context",
            "get_user_constraints",
            "get_relevant_facts",
            "suggest_replan_candidates",
            "validate_week_coherence",
        ),
        allowed_actions=("PlanPatch", "pending_resolution", "memory_actions"),
        required_truth_blocks=("temporal", "planning", "execution_reality"),
        optional_truth_blocks=("working_memory", "active_thread", "pending_confirmation"),
        output_schema="CoachDecision",
        final_reply_mode="post_runtime",
        max_context_blocks=(
            "temporal",
            "planning",
            "execution",
            "working_memory",
            "active_thread",
            "pending_confirmation",
        ),
    ),
    "conversation_health_signal": PromptContract(
        name="conversation_health_signal",
        capability="write_after_validation",
        allowed_tools=("get_plan_window", "get_load_context", "get_relevant_facts"),
        allowed_actions=("record_health_signal", "PlanPatch"),
        required_truth_blocks=("temporal", "working_memory", "planning"),
        optional_truth_blocks=("execution_reality", "active_thread"),
        output_schema="CoachDecision",
        final_reply_mode="post_runtime",
        max_context_blocks=("temporal", "working_memory", "planning", "execution"),
    ),
    "conversation_activity_review": PromptContract(
        name="conversation_activity_review",
        capability="read_only",
        allowed_tools=("get_recent_activities",),
        allowed_actions=(),
        required_truth_blocks=("temporal", "execution_reality"),
        optional_truth_blocks=("planning",),
        output_schema="grounded_final_reply",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "execution"),
    ),
    "conversation_activity_highlights": PromptContract(
        name="conversation_activity_highlights",
        capability="read_only",
        allowed_tools=("get_recent_activities",),
        allowed_actions=(),
        required_truth_blocks=("temporal", "execution_reality"),
        optional_truth_blocks=(),
        output_schema="grounded_final_reply",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "execution"),
    ),
    "conversation_load_review": PromptContract(
        name="conversation_load_review",
        capability="read_only",
        allowed_tools=("get_load_context", "get_recent_activities"),
        allowed_actions=(),
        required_truth_blocks=("temporal", "execution_reality", "load_context"),
        optional_truth_blocks=("signals", "planning"),
        output_schema="grounded_final_reply",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "execution", "signals", "planning"),
    ),
    "conversation_fact_recall": PromptContract(
        name="conversation_fact_recall",
        capability="read_only",
        allowed_tools=("get_relevant_facts",),
        allowed_actions=(),
        required_truth_blocks=("memory",),
        optional_truth_blocks=("temporal",),
        output_schema="grounded_final_reply",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "memory", "conversation_frame"),
    ),
    "conversation_generic_question": PromptContract(
        name="conversation_generic_question",
        capability="read_only",
        allowed_tools=("get_plan_window", "get_relevant_facts"),
        allowed_actions=(),
        required_truth_blocks=("temporal",),
        optional_truth_blocks=("planning", "memory", "execution_reality"),
        output_schema="grounded_final_reply",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "planning", "memory", "execution"),
    ),
}


def get_prompt_contract(name: str) -> PromptContract:
    return _PROMPT_CONTRACTS[name]


def list_prompt_contracts() -> tuple[PromptContract, ...]:
    return tuple(_PROMPT_CONTRACTS.values())
