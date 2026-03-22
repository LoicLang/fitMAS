from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from fitmas.activity_claims import (
    ActivityClaim,
    build_claim_correction_payloads,
    build_claim_fact_payloads,
    extract_activity_claim,
    extract_recent_activity_claim,
    format_activity_claim_for_prompt,
    is_activity_claim_correction,
)
from fitmas.execution_context import (
    TodayExecutionContext,
    build_today_execution_context,
    format_execution_context_for_prompt,
)
from fitmas.fact_memory import normalize_fact_payload, select_relevant_facts
from fitmas.signals import Signal, format_signals_for_prompt, select_conversation_signals
from fitmas.temporal_resolver import (
    TemporalResolution,
    format_temporal_resolution_for_prompt,
    resolve_temporal_context,
)
from fitmas.time_context import build_time_context


@dataclass(frozen=True, slots=True)
class ConversationContextBundle:
    time_context: dict[str, str]
    temporal_resolution: TemporalResolution
    execution_context: TodayExecutionContext
    previous_activity_claim: ActivityClaim | None
    current_activity_claim: ActivityClaim | None
    recent_activity_claim: ActivityClaim | None
    active_facts: tuple[dict[str, Any], ...]
    selected_facts: tuple[str, ...]
    selected_signals: tuple[Signal, ...]


def build_conversation_context(
    *,
    user_text: str,
    conversation_history: Sequence[dict[str, Any]],
    timezone_name: str | None,
    scheduled_sessions: Sequence[Any],
    activities: Sequence[Any],
    active_facts: Sequence[dict[str, Any]],
    signals: Sequence[Signal] | None = None,
    now: datetime | None = None,
) -> ConversationContextBundle:
    normalized_facts = tuple(_normalize_facts(active_facts))
    selected_signals = tuple(select_conversation_signals(list(signals or [])))
    return ConversationContextBundle(
        time_context=build_time_context(timezone_name, now=now),
        temporal_resolution=resolve_temporal_context(
            user_text,
            timezone_name=timezone_name,
            now=now,
        ),
        execution_context=build_today_execution_context(
            timezone_name=timezone_name,
            scheduled_sessions=scheduled_sessions,
            activities=activities,
            now=now,
        ),
        previous_activity_claim=extract_recent_activity_claim(
            conversation_history,
            current_text="",
            timezone_name=timezone_name,
            now=now,
        ),
        current_activity_claim=extract_activity_claim(
            user_text,
            timezone_name=timezone_name,
            now=now,
        ),
        recent_activity_claim=extract_recent_activity_claim(
            conversation_history,
            current_text=user_text,
            timezone_name=timezone_name,
            now=now,
        ),
        active_facts=normalized_facts,
        selected_facts=tuple(select_relevant_facts(normalized_facts, affects=["conversation"], limit=6, now=now)),
        selected_signals=selected_signals,
    )


def build_claim_memory_updates(
    context: ConversationContextBundle,
    *,
    activities: Sequence[Any],
    timezone_name: str | None,
    user_text: str,
) -> list[dict[str, Any]]:
    if context.current_activity_claim is None:
        return []

    updates = build_claim_fact_payloads(
        context.recent_activity_claim,
        activities=activities,
        timezone_name=timezone_name,
    )
    if is_activity_claim_correction(user_text, timezone_name=timezone_name):
        updates.extend(
            build_claim_correction_payloads(
                context.previous_activity_claim,
                context.recent_activity_claim,
            )
        )
    return updates


def execution_summary_for_prompt(context: ConversationContextBundle) -> str:
    return format_execution_context_for_prompt(context.execution_context)


def temporal_summary_for_prompt(context: ConversationContextBundle) -> str:
    return format_temporal_resolution_for_prompt(context.temporal_resolution)


def activity_claim_summary_for_prompt(context: ConversationContextBundle) -> str:
    return format_activity_claim_for_prompt(context.recent_activity_claim)


def signal_summary_for_prompt(context: ConversationContextBundle) -> str:
    return format_signals_for_prompt(list(context.selected_signals))


def _normalize_facts(facts: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_fact_payload(dict(fact)) for fact in facts]
