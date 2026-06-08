from fitmas.legacy.llm.prompt_contracts import get_prompt_contract, list_prompt_contracts
from fitmas.legacy.tools.registry import build_tool_registry


def test_plan_lookup_contract_is_read_only() -> None:
    contract = get_prompt_contract("conversation_plan_lookup")

    assert contract.name == "conversation_plan_lookup"
    assert contract.capability == "read_only"
    assert contract.allowed_tools == ("get_plan_window",)
    assert contract.allowed_actions == ()
    assert contract.decision_output_schema == "CoachDecision"
    assert contract.output_schema == "grounded_final_reply"
    assert contract.final_reply_mode == "terminal_composer"
    assert "temporal" in contract.required_truth_blocks
    assert "plan_window" in contract.required_truth_blocks


def test_plan_negotiation_contract_uses_read_and_validation_tools_only() -> None:
    contract = get_prompt_contract("conversation_plan_negotiation")

    assert contract.capability == "draft_action"
    assert contract.allowed_tools == (
        "get_plan_window",
        "resolve_planning_window",
        "get_user_constraints",
        "validate_plan_patch",
    )
    assert len(contract.allowed_tools) == 4
    assert not any(tool.startswith("draft_") for tool in contract.allowed_tools)
    assert "suggest_replan_candidates" not in contract.allowed_tools
    assert "get_recent_activities" not in contract.allowed_tools
    assert "get_activity_highlights" not in contract.allowed_tools
    assert "get_recent_reality_window" not in contract.allowed_tools
    assert "get_load_context" not in contract.allowed_tools
    assert "validate_week_coherence" not in contract.allowed_tools
    assert "PlanPatch" in contract.allowed_actions
    assert contract.decision_output_schema == "CoachDecision"
    assert contract.output_schema == "CoachDecision"
    assert contract.final_reply_mode == "post_runtime"


def test_availability_constraint_contract_uses_small_candidate_surface() -> None:
    contract = get_prompt_contract("conversation_availability_constraint")

    assert contract.capability == "write_after_validation"
    assert contract.allowed_tools == (
        "resolve_planning_window",
        "get_plan_window",
        "get_user_constraints",
    )
    assert "record_availability" in contract.allowed_actions
    assert "PlanPatch" not in contract.allowed_actions
    assert not any(tool.startswith("draft_") for tool in contract.allowed_tools)
    assert "suggest_replan_candidates" not in contract.allowed_tools
    assert "validate_plan_patch" not in contract.allowed_tools
    assert "validate_week_coherence" not in contract.allowed_tools


def test_health_signal_contract_keeps_small_adaptation_surface() -> None:
    contract = get_prompt_contract("conversation_health_signal")

    assert contract.capability == "write_after_validation"
    assert contract.allowed_tools == (
        "get_plan_window",
        "get_user_constraints",
        "validate_plan_patch",
    )
    assert "get_today_context" not in contract.allowed_tools
    assert "get_load_context" not in contract.allowed_tools
    assert "validate_week_coherence" not in contract.allowed_tools


def test_close_turn_contract_matches_decide_fallback_runtime() -> None:
    contract = get_prompt_contract("conversation_close_turn")

    assert contract.capability == "terminal_text"
    assert contract.allowed_tools == ()
    assert contract.allowed_actions == ()
    assert contract.decision_output_schema == "CoachDecision"
    assert contract.output_schema == "final_text"


def test_casual_chat_contract_matches_current_decide_runtime() -> None:
    contract = get_prompt_contract("conversation_casual_chat")

    assert contract.capability == "terminal_text"
    assert contract.allowed_tools == ()
    assert contract.allowed_actions == ()
    assert contract.decision_output_schema == "CoachDecision"
    assert contract.output_schema == "final_text"


def test_generic_question_contract_is_general_answer() -> None:
    contract = get_prompt_contract("conversation_generic_question")

    assert contract.capability == "general_answer"
    assert contract.allowed_tools == ("get_coach_lens", "get_relevant_facts")
    assert contract.allowed_actions == ()
    assert contract.final_reply_mode == "terminal_composer"
    assert "planning" not in contract.optional_truth_blocks


def test_activity_highlights_contract_uses_highlight_tool() -> None:
    contract = get_prompt_contract("conversation_activity_highlights")

    assert contract.capability == "read_only"
    assert contract.allowed_tools == ("get_activity_highlights",)
    assert contract.allowed_actions == ()
    assert contract.final_reply_mode == "terminal_composer"


def test_contracts_distinguish_current_decision_output_from_final_output() -> None:
    plan_lookup = get_prompt_contract("conversation_plan_lookup")
    close_turn = get_prompt_contract("conversation_close_turn")

    assert plan_lookup.decision_output_schema == "CoachDecision"
    assert plan_lookup.output_schema == "grounded_final_reply"
    assert close_turn.decision_output_schema == "CoachDecision"
    assert close_turn.output_schema == "final_text"


def test_conversation_prompt_contract_tools_are_registered() -> None:
    registry = build_tool_registry()

    for contract in list_prompt_contracts():
        for tool_name in contract.allowed_tools:
            assert tool_name in registry
            assert "conversation" in registry[tool_name].allowed_pipelines
