from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from .explanation import DecisionExplanation


DecisionOutcomeKind = Literal[
    "answer",
    "clarification",
    "memory_updated",
    "execution_updated",
    "plan_committed",
    "plan_pending",
    "plan_choice_pending",
    "plan_blocked",
    "no_send",
]
CommandDomain = Literal["planning", "execution", "memory"]
CommandStatus = Literal["applied", "blocked", "skipped"]


@dataclass(frozen=True, slots=True)
class ReplyContract:
    mode: str
    audience: str
    allowed_claims: tuple[str, ...]
    forbidden_claims: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Command:
    id: str
    domain: CommandDomain
    name: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CommandResult:
    command_id: str
    domain: CommandDomain
    name: str
    status: CommandStatus
    event_id: str | None
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.status == "applied" and not self.event_id:
            raise ValueError("applied command results must reference an event")


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    kind: DecisionOutcomeKind
    commands: tuple[Command, ...]
    applied_commands: tuple[CommandResult, ...]
    candidates: tuple[Any, ...]
    selected_candidate_id: str | None
    explanation: DecisionExplanation
    reply_contract: ReplyContract
