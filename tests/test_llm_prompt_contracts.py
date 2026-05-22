from __future__ import annotations

from fitmas.llm.prompts.contracts import (
    REPLY_PROMPT_CONTRACT,
    REVIEWER_PROMPT_CONTRACT,
    UNDERSTANDING_PROMPT_CONTRACT,
    list_canonical_prompt_contracts,
)


def test_phase6_has_exactly_three_canonical_prompt_families() -> None:
    contracts = list_canonical_prompt_contracts()

    assert tuple(contract.family for contract in contracts) == ("understanding", "reviewer", "reply")


def test_understanding_contract_cannot_write_or_speak() -> None:
    contract = UNDERSTANDING_PROMPT_CONTRACT

    assert contract.family == "understanding"
    assert contract.output_schema == "CoachUnderstanding"
    assert contract.can_write is False
    assert contract.can_speak_to_user is False
    assert contract.allowed_outputs == ("intent", "signals", "requested_change", "pending_resolution", "clarification_need")
    assert "PlanPatch" in contract.forbidden_outputs
    assert "final_reply" in contract.forbidden_outputs


def test_reviewer_contract_only_selects_candidates() -> None:
    contract = REVIEWER_PROMPT_CONTRACT

    assert contract.family == "reviewer"
    assert contract.output_schema == "CandidateReviewDecision"
    assert contract.can_write is False
    assert contract.can_speak_to_user is False
    assert contract.allowed_outputs == ("preferred_candidate_id", "confidence", "rationale")


def test_reply_contract_can_speak_but_not_write() -> None:
    contract = REPLY_PROMPT_CONTRACT

    assert contract.family == "reply"
    assert contract.output_schema == "final_text"
    assert contract.can_write is False
    assert contract.can_speak_to_user is True
