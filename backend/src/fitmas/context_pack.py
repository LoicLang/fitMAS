from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


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
