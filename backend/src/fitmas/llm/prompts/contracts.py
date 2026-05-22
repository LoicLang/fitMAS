from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PromptFamily = Literal["understanding", "reviewer", "reply"]


@dataclass(frozen=True, slots=True)
class CanonicalPromptContract:
    name: str
    family: PromptFamily
    output_schema: str
    allowed_outputs: tuple[str, ...]
    forbidden_outputs: tuple[str, ...]
    can_write: bool
    can_speak_to_user: bool


UNDERSTANDING_PROMPT_CONTRACT = CanonicalPromptContract(
    name="decision_understanding",
    family="understanding",
    output_schema="CoachUnderstanding",
    allowed_outputs=("intent", "signals", "requested_change", "pending_resolution", "clarification_need"),
    forbidden_outputs=("final_reply", "reply_text", "fitmas_message", "PlanPatch", "MutationDecision", "commands"),
    can_write=False,
    can_speak_to_user=False,
)

REVIEWER_PROMPT_CONTRACT = CanonicalPromptContract(
    name="planning_candidate_reviewer",
    family="reviewer",
    output_schema="CandidateReviewDecision",
    allowed_outputs=("preferred_candidate_id", "confidence", "rationale"),
    forbidden_outputs=("PlanPatch", "operations", "final_reply", "reply_text", "commands"),
    can_write=False,
    can_speak_to_user=False,
)

REPLY_PROMPT_CONTRACT = CanonicalPromptContract(
    name="decision_reply",
    family="reply",
    output_schema="final_text",
    allowed_outputs=("final_text",),
    forbidden_outputs=("commands", "PlanPatch", "MutationDecision"),
    can_write=False,
    can_speak_to_user=True,
)


def list_canonical_prompt_contracts() -> tuple[CanonicalPromptContract, ...]:
    return (UNDERSTANDING_PROMPT_CONTRACT, REVIEWER_PROMPT_CONTRACT, REPLY_PROMPT_CONTRACT)
