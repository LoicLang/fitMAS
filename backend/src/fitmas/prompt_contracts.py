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
    decision_output_schema: str
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
        decision_output_schema="CoachDecision",
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
        decision_output_schema="CoachDecision",
        output_schema="final_text",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "conversation_frame"),
    ),
    "conversation_needs_clarification": PromptContract(
        name="conversation_needs_clarification",
        capability="terminal_text",
        allowed_tools=(),
        allowed_actions=(),
        required_truth_blocks=("conversation_frame",),
        optional_truth_blocks=("temporal",),
        decision_output_schema="CoachDecision",
        output_schema="final_text",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "conversation_frame"),
    ),
    "conversation_calibration_answer": PromptContract(
        name="conversation_calibration_answer",
        capability="terminal_text",
        allowed_tools=(),
        allowed_actions=(),
        required_truth_blocks=("conversation_frame",),
        optional_truth_blocks=("temporal",),
        decision_output_schema="CoachDecision",
        output_schema="final_text",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "conversation_frame"),
    ),
    "conversation_plan_lookup": PromptContract(
        name="conversation_plan_lookup",
        capability="read_only",
        allowed_tools=("get_plan_window",),
        allowed_actions=(),
        required_truth_blocks=("temporal", "plan_window"),
        optional_truth_blocks=("execution_reality", "activity_claims"),
        decision_output_schema="CoachDecision",
        output_schema="grounded_final_reply",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "planning", "execution", "conversation_frame"),
    ),
    "conversation_execution_report": PromptContract(
        name="conversation_execution_report",
        capability="write_after_validation",
        allowed_tools=("get_recent_activities",),
        allowed_actions=("record_execution_update", "record_memory"),
        required_truth_blocks=("temporal", "execution_reality", "planning"),
        optional_truth_blocks=("activity_claims", "conversation_frame"),
        decision_output_schema="CoachDecision",
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
        ),
        allowed_actions=("PlanPatch", "pending_resolution", "memory_actions"),
        required_truth_blocks=("temporal", "planning", "execution_reality"),
        optional_truth_blocks=("working_memory", "active_thread", "pending_confirmation"),
        decision_output_schema="CoachDecision",
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
        allowed_tools=(
            "get_today_context",
            "get_plan_window",
            "get_load_context",
            "get_relevant_facts",
            "draft_lighten_day",
            "draft_replace_session",
            "validate_plan_patch",
            "validate_week_coherence",
        ),
        allowed_actions=("record_health_signal", "PlanPatch"),
        required_truth_blocks=("temporal", "working_memory", "planning"),
        optional_truth_blocks=("execution_reality", "active_thread"),
        decision_output_schema="CoachDecision",
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
        decision_output_schema="CoachDecision",
        output_schema="grounded_final_reply",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "execution"),
    ),
    "conversation_activity_highlights": PromptContract(
        name="conversation_activity_highlights",
        capability="read_only",
        allowed_tools=("get_activity_highlights",),
        allowed_actions=(),
        required_truth_blocks=("temporal", "execution_reality"),
        optional_truth_blocks=(),
        decision_output_schema="CoachDecision",
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
        decision_output_schema="CoachDecision",
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
        decision_output_schema="CoachDecision",
        output_schema="grounded_final_reply",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "memory", "conversation_frame"),
    ),
    "conversation_generic_question": PromptContract(
        name="conversation_generic_question",
        capability="general_answer",
        allowed_tools=("get_coach_lens", "get_relevant_facts"),
        allowed_actions=(),
        required_truth_blocks=("conversation_frame",),
        optional_truth_blocks=("temporal", "memory"),
        decision_output_schema="CoachDecision",
        output_schema="final_text",
        final_reply_mode="terminal_composer",
        max_context_blocks=("temporal", "memory", "conversation_frame"),
    ),
}


def get_prompt_contract(name: str) -> PromptContract:
    return _PROMPT_CONTRACTS[name]


def list_prompt_contracts() -> tuple[PromptContract, ...]:
    return tuple(_PROMPT_CONTRACTS.values())
