from __future__ import annotations

from dataclasses import dataclass

from fitmas.tools.routing import IntentCategory


@dataclass(frozen=True, slots=True)
class ConversationPromptPolicy:
    name: str
    history_limit: int
    contract_name: str | None = None
    include_plan_summary: bool = False
    include_timeline: bool = True
    include_execution: bool = True
    include_temporal: bool = True
    include_claim: bool = True
    include_signals: bool = True
    include_facts: bool = True
    include_coach_context: bool = True
    include_open_question_marker: bool = True


# Maps intent categories to prompt policies for context compaction.
_INTENT_POLICIES: dict[IntentCategory, ConversationPromptPolicy] = {
    IntentCategory.CLOSE_TURN: ConversationPromptPolicy(
        name="casual_close",
        contract_name="conversation_close_turn",
        history_limit=3,
        include_plan_summary=False,
        include_timeline=False,
        include_execution=False,
        include_temporal=True,
        include_claim=False,
        include_signals=False,
        include_facts=False,
        include_coach_context=False,
        include_open_question_marker=False,
    ),
    IntentCategory.CASUAL_CHAT: ConversationPromptPolicy(
        name="casual_compact",
        contract_name="conversation_casual_chat",
        history_limit=6,
        include_plan_summary=False,
        include_timeline=False,
        include_execution=False,
        include_temporal=True,
        include_claim=False,
        include_signals=False,
        include_facts=False,
        include_coach_context=False,
        include_open_question_marker=False,
    ),
    IntentCategory.NEEDS_CLARIFICATION: ConversationPromptPolicy(
        name="clarification_compact",
        contract_name="conversation_needs_clarification",
        history_limit=4,
        include_plan_summary=False,
        include_timeline=False,
        include_execution=False,
        include_temporal=True,
        include_claim=False,
        include_signals=False,
        include_facts=False,
        include_coach_context=False,
        include_open_question_marker=True,
    ),
    IntentCategory.CALIBRATION_ANSWER: ConversationPromptPolicy(
        name="calibration_answer_compact",
        contract_name="conversation_calibration_answer",
        history_limit=4,
        include_plan_summary=False,
        include_timeline=False,
        include_execution=False,
        include_temporal=True,
        include_claim=False,
        include_signals=False,
        include_facts=False,
        include_coach_context=False,
        include_open_question_marker=False,
    ),
    IntentCategory.EXECUTION_REPORT: ConversationPromptPolicy(
        name="execution_report",
        contract_name="conversation_execution_report",
        history_limit=4,
        include_plan_summary=False,
        include_timeline=True,
        include_execution=True,
        include_temporal=True,
        include_claim=True,
        include_signals=False,
        include_facts=False,
    ),
    IntentCategory.HEALTH_SIGNAL: ConversationPromptPolicy(
        name="health_signal",
        contract_name="conversation_health_signal",
        history_limit=4,
        include_plan_summary=False,
        include_timeline=True,
        include_execution=True,
        include_temporal=True,
        include_claim=True,
        include_signals=True,
        include_facts=True,
    ),
    IntentCategory.PLAN_NEGOTIATION: ConversationPromptPolicy(
        name="plan_negotiation_full",
        contract_name="conversation_plan_negotiation",
        history_limit=6,
        include_plan_summary=False,
        include_timeline=True,
        include_execution=True,
        include_temporal=True,
        include_claim=True,
        include_signals=True,
        include_facts=True,
    ),
    IntentCategory.PLAN_LOOKUP: ConversationPromptPolicy(
        name="plan_lookup_compact",
        contract_name="conversation_plan_lookup",
        history_limit=4,
        include_plan_summary=False,
        include_timeline=True,
        include_execution=True,
        include_temporal=True,
        include_claim=True,
        include_signals=False,
        include_facts=False,
        include_coach_context=False,
        include_open_question_marker=False,
    ),
    IntentCategory.ACTIVITY_REVIEW: ConversationPromptPolicy(
        name="recent_activities_compact",
        contract_name="conversation_activity_review",
        history_limit=3,
        include_plan_summary=False,
        include_timeline=False,
        include_execution=False,
        include_temporal=True,
        include_claim=False,
        include_signals=False,
        include_facts=False,
        include_coach_context=False,
        include_open_question_marker=False,
    ),
    IntentCategory.ACTIVITY_HIGHLIGHTS: ConversationPromptPolicy(
        name="activity_highlights_compact",
        contract_name="conversation_activity_highlights",
        history_limit=2,
        include_plan_summary=False,
        include_timeline=False,
        include_execution=False,
        include_temporal=True,
        include_claim=False,
        include_signals=False,
        include_facts=False,
        include_coach_context=False,
        include_open_question_marker=False,
    ),
    IntentCategory.LOAD_REVIEW: ConversationPromptPolicy(
        name="load_review",
        contract_name="conversation_load_review",
        history_limit=4,
        include_plan_summary=False,
        include_timeline=True,
        include_execution=True,
        include_temporal=True,
        include_claim=False,
        include_signals=True,
        include_facts=False,
        include_coach_context=False,
        include_open_question_marker=False,
    ),
    IntentCategory.FACT_RECALL: ConversationPromptPolicy(
        name="fact_recall_compact",
        contract_name="conversation_fact_recall",
        history_limit=3,
        include_plan_summary=False,
        include_timeline=False,
        include_execution=False,
        include_temporal=True,
        include_claim=False,
        include_signals=False,
        include_facts=True,
        include_coach_context=False,
        include_open_question_marker=False,
    ),
    IntentCategory.GENERIC_QUESTION: ConversationPromptPolicy(
        name="generic_question_compact",
        contract_name="conversation_generic_question",
        history_limit=4,
        include_plan_summary=False,
        include_timeline=False,
        include_execution=False,
        include_temporal=True,
        include_claim=False,
        include_signals=False,
        include_facts=True,
        include_coach_context=False,
        include_open_question_marker=False,
    ),
}


def list_conversation_prompt_policies() -> tuple[ConversationPromptPolicy, ...]:
    return tuple(_INTENT_POLICIES.values())


def select_conversation_prompt_policy(
    *,
    routing_reason: str | None = None,
    intent: IntentCategory | None = None,
) -> ConversationPromptPolicy:
    """Select prompt policy based on intent category (preferred) or legacy routing_reason."""
    # Prefer intent-based lookup
    if intent is not None and intent in _INTENT_POLICIES:
        return _INTENT_POLICIES[intent]

    # Legacy fallback for backward compatibility
    if routing_reason in ("plan_lookup", "plan_dispute"):
        return _INTENT_POLICIES[IntentCategory.PLAN_LOOKUP]
    if routing_reason == "activity_highlights":
        return _INTENT_POLICIES[IntentCategory.ACTIVITY_HIGHLIGHTS]
    if routing_reason == "recent_activities":
        return _INTENT_POLICIES[IntentCategory.ACTIVITY_REVIEW]
    if routing_reason == "fact_recall":
        return _INTENT_POLICIES[IntentCategory.FACT_RECALL]
    if routing_reason == "generic_lookup":
        return _INTENT_POLICIES[IntentCategory.GENERIC_QUESTION]

    return ConversationPromptPolicy(
        name="default_full",
        contract_name=None,
        history_limit=8,
        include_plan_summary=False,
    )
