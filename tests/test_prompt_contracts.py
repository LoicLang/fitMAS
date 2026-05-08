from fitmas.prompt_contracts import get_prompt_contract


def test_plan_lookup_contract_is_read_only() -> None:
    contract = get_prompt_contract("conversation_plan_lookup")

    assert contract.name == "conversation_plan_lookup"
    assert contract.capability == "read_only"
    assert contract.allowed_actions == ()
    assert contract.decision_output_schema == "CoachDecision"
    assert contract.output_schema == "grounded_final_reply"
    assert contract.final_reply_mode == "terminal_composer"
    assert "temporal" in contract.required_truth_blocks
    assert "plan_window" in contract.required_truth_blocks


def test_plan_negotiation_contract_can_draft_plan_patch() -> None:
    contract = get_prompt_contract("conversation_plan_negotiation")

    assert contract.capability == "draft_action"
    assert "PlanPatch" in contract.allowed_actions
    assert contract.decision_output_schema == "CoachDecision"
    assert contract.output_schema == "CoachDecision"
    assert contract.final_reply_mode == "post_runtime"


def test_close_turn_contract_is_terminal_text() -> None:
    contract = get_prompt_contract("conversation_close_turn")

    assert contract.capability == "terminal_text"
    assert contract.allowed_tools == ()
    assert contract.allowed_actions == ()
    assert contract.decision_output_schema == "final_text"
    assert contract.output_schema == "final_text"


def test_casual_chat_contract_matches_current_decide_runtime() -> None:
    contract = get_prompt_contract("conversation_casual_chat")

    assert contract.capability == "terminal_text"
    assert contract.allowed_tools == ()
    assert contract.allowed_actions == ()
    assert contract.decision_output_schema == "CoachDecision"
    assert contract.output_schema == "final_text"


def test_contracts_distinguish_current_decision_output_from_final_output() -> None:
    plan_lookup = get_prompt_contract("conversation_plan_lookup")
    close_turn = get_prompt_contract("conversation_close_turn")

    assert plan_lookup.decision_output_schema == "CoachDecision"
    assert plan_lookup.output_schema == "grounded_final_reply"
    assert close_turn.decision_output_schema == close_turn.output_schema == "final_text"
