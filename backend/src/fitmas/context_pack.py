from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class TurnScope:
    route: str
    intent: str | None
    capability: str


@dataclass(frozen=True, slots=True)
class TemporalContext:
    time_context: Mapping[str, str] | None = None
    temporal_summary: str | None = None


@dataclass(frozen=True, slots=True)
class PlanningContext:
    timeline_summary: str | None = None
    plan_summary: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionReality:
    execution_summary: str | None = None
    activity_claim_summary: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryContext:
    durable_profile: tuple[str, ...] = ()
    working_memory: tuple[str, ...] = ()
    execution_reality: tuple[str, ...] = ()
    conversation_frame: tuple[str, ...] = ()

    def family_names(self) -> tuple[str, ...]:
        return (
            "durable_profile",
            "working_memory",
            "execution_reality",
            "conversation_frame",
        )


@dataclass(frozen=True, slots=True)
class ActiveThreadContext:
    history_messages: tuple[Mapping[str, Any], ...] = ()
    open_question: str | None = None
    pending_summary: str | None = None


@dataclass(frozen=True, slots=True)
class CoachProfileContext:
    summary: str | None = None
    style: str | None = None


@dataclass(frozen=True, slots=True)
class ToolBudget:
    allowed_tools: tuple[str, ...] = ()
    tool_choice: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationContextPack:
    turn_scope: TurnScope
    temporal: TemporalContext
    planning: PlanningContext
    execution: ExecutionReality
    memory: MemoryContext
    active_thread: ActiveThreadContext
    coach_profile: CoachProfileContext
    tool_budget: ToolBudget
    grounding: Any | None = None

    def truth_block_names(self) -> tuple[str, ...]:
        return (
            "temporal",
            "planning",
            "execution",
            "memory",
            "active_thread",
            "coach_profile",
            "tool_budget",
        )


def build_conversation_context_pack(
    *,
    route: str,
    intent: str | None,
    capability: str,
    time_context: Mapping[str, str] | None = None,
    temporal_summary: str | None = None,
    timeline_summary: str | None = None,
    plan_summary: str | None = None,
    execution_summary: str | None = None,
    activity_claim_summary: str | None = None,
    selected_facts: Sequence[str] = (),
    working_facts: Sequence[str] = (),
    execution_facts: Sequence[str] = (),
    conversation_frame: Sequence[str] = (),
    history_messages: Sequence[Mapping[str, Any]] = (),
    open_question: str | None = None,
    pending_summary: str | None = None,
    coach_summary: str | None = None,
    coach_style: str | None = None,
    allowed_tools: Sequence[str] = (),
    tool_choice: str | None = None,
    grounding: Any | None = None,
) -> ConversationContextPack:
    return ConversationContextPack(
        turn_scope=TurnScope(route=route, intent=intent, capability=capability),
        temporal=TemporalContext(time_context=time_context, temporal_summary=temporal_summary),
        planning=PlanningContext(timeline_summary=timeline_summary, plan_summary=plan_summary),
        execution=ExecutionReality(
            execution_summary=execution_summary,
            activity_claim_summary=activity_claim_summary,
        ),
        memory=MemoryContext(
            durable_profile=tuple(selected_facts),
            working_memory=tuple(working_facts),
            execution_reality=tuple(execution_facts),
            conversation_frame=tuple(conversation_frame),
        ),
        active_thread=ActiveThreadContext(
            history_messages=tuple(history_messages),
            open_question=open_question,
            pending_summary=pending_summary,
        ),
        coach_profile=CoachProfileContext(summary=coach_summary, style=coach_style),
        tool_budget=ToolBudget(allowed_tools=tuple(allowed_tools), tool_choice=tool_choice),
        grounding=grounding,
    )
