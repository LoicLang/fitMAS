from fitmas.conversation_prompting import list_conversation_prompt_policies
from fitmas.llm.prompt_contracts import get_prompt_contract


def test_every_intent_prompt_policy_contract_resolves() -> None:
    policies = list_conversation_prompt_policies()

    assert policies
    for policy in policies:
        assert policy.contract_name is not None
        assert get_prompt_contract(policy.contract_name).name == policy.contract_name


def test_terminal_prompt_policy_contracts_have_no_tools_or_actions() -> None:
    contracts = {
        policy.contract_name: get_prompt_contract(policy.contract_name)
        for policy in list_conversation_prompt_policies()
        if policy.contract_name in {"conversation_close_turn", "conversation_casual_chat"}
    }

    assert set(contracts) == {"conversation_close_turn", "conversation_casual_chat"}
    for contract in contracts.values():
        assert contract.capability == "terminal_text"
        assert contract.allowed_tools == ()
        assert contract.allowed_actions == ()
        assert contract.final_reply_mode == "terminal_composer"


def test_plan_negotiation_is_the_only_draft_action_policy() -> None:
    draft_action_contracts = [
        get_prompt_contract(policy.contract_name)
        for policy in list_conversation_prompt_policies()
        if get_prompt_contract(policy.contract_name).capability == "draft_action"
    ]

    assert [contract.name for contract in draft_action_contracts] == ["conversation_plan_negotiation"]
    assert "PlanPatch" in draft_action_contracts[0].allowed_actions


def test_read_only_policy_contracts_do_not_allow_actions() -> None:
    read_only_contracts = [
        get_prompt_contract(policy.contract_name)
        for policy in list_conversation_prompt_policies()
        if get_prompt_contract(policy.contract_name).capability == "read_only"
    ]

    assert read_only_contracts
    for contract in read_only_contracts:
        assert contract.allowed_actions == ()
