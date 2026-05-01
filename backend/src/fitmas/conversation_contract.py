from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fitmas.llm import CoachDecision, MutationDecision
from fitmas.models import DayId, Extraction


@dataclass(slots=True)
class ConversationTurnInput:
    text: str


@dataclass(slots=True)
class ConversationTurnState:
    user: Any
    conversation_history: list[dict[str, Any]]
    previous_agent_text: str | None
    scheduled_sessions: list[Any]
    timeline: list[Any]
    activities: list[Any]
    today_session: Any | None
    active_memory_rows: list[Any]
    active_facts: list[dict[str, Any]]


@dataclass(slots=True)
class ConversationTurnOutcome:
    extraction: Extraction
    reply_text: str
    day_updated: DayId | None = None
    response_mode: str = "reply"
    decision: MutationDecision | None = None
    mutation_applied: bool = False
    pending_confirmation: bool = False
    pending_confirmation_id: int | None = None


@dataclass(frozen=True, slots=True)
class ConversationPipelineDependencies:
    decide: Callable[..., CoachDecision | MutationDecision | None]
    extract_facts: Callable[[str, str, list[dict[str, Any]]], list[dict[str, Any]]]
    check_and_adapt_health_facts: Callable[..., Any]
    plan_turn: Callable[..., Any]


class ConversationUserNotFoundError(RuntimeError):
    pass
