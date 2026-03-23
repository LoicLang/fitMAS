from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversationPromptPolicy:
    name: str
    history_limit: int
    include_plan_summary: bool = True
    include_timeline: bool = True
    include_execution: bool = True
    include_temporal: bool = True
    include_claim: bool = True
    include_signals: bool = True
    include_facts: bool = True
    include_coach_context: bool = True


def select_conversation_prompt_policy(*, routing_reason: str | None) -> ConversationPromptPolicy:
    if routing_reason in ("plan_lookup", "plan_dispute"):
        return ConversationPromptPolicy(
            name="plan_lookup_compact",
            history_limit=4,
            include_plan_summary=False,
            include_timeline=True,
            include_execution=True,
            include_temporal=True,
            include_claim=True,
            include_signals=False,
            include_facts=False,
        )
    if routing_reason == "activity_highlights":
        return ConversationPromptPolicy(
            name="activity_highlights_compact",
            history_limit=2,
            include_plan_summary=False,
            include_timeline=False,
            include_execution=False,
            include_temporal=True,
            include_claim=False,
            include_signals=False,
            include_facts=False,
        )
    if routing_reason == "recent_activities":
        return ConversationPromptPolicy(
            name="recent_activities_compact",
            history_limit=3,
            include_plan_summary=False,
            include_timeline=False,
            include_execution=False,
            include_temporal=True,
            include_claim=False,
            include_signals=False,
            include_facts=False,
        )
    if routing_reason == "fact_recall":
        return ConversationPromptPolicy(
            name="fact_recall_compact",
            history_limit=3,
            include_plan_summary=False,
            include_timeline=False,
            include_execution=False,
            include_temporal=True,
            include_claim=False,
            include_signals=False,
            include_facts=True,
        )
    if routing_reason == "generic_lookup":
        return ConversationPromptPolicy(
            name="generic_lookup_compact",
            history_limit=4,
            include_plan_summary=False,
            include_timeline=True,
            include_execution=True,
            include_temporal=True,
            include_claim=False,
            include_signals=False,
            include_facts=False,
        )
    return ConversationPromptPolicy(name="default_full", history_limit=8, include_plan_summary=False)
