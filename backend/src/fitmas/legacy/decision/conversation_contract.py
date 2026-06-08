from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fitmas.legacy.domain.planning.mutation_decision import MutationDecision
from fitmas.legacy.decision.message_models import Extraction
from fitmas.legacy.domain.planning.view_models import DayId


def _no_calibration_resolution(**_: Any) -> Any:
    return None


@dataclass(slots=True)
class ConversationTurnInput:
    text: str
    client_message_key: str | None = None
    source: str | None = None


@dataclass(slots=True)
class ConversationTurnState:
    user: Any
    current_user_message_id: int
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
    extract_facts: Callable[[str, str, list[dict[str, Any]]], list[dict[str, Any]]]
    check_and_adapt_health_facts: Callable[..., Any]
    plan_turn: Callable[..., Any]
    resolve_calibration_need: Callable[..., Any] = _no_calibration_resolution


class ConversationUserNotFoundError(RuntimeError):
    pass
