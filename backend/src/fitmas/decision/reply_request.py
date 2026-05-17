from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from .explanation import DecisionExplanation
from .outcome import ReplyContract


ReplyRequestKind = Literal[
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


@dataclass(frozen=True, slots=True)
class ReplyRequest:
    kind: ReplyRequestKind
    user_text: str
    committed_events: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    pending_summary: str | None
    memory_updates: tuple[str, ...]
    execution_updates: tuple[str, ...]
    candidate_summaries: tuple[str, ...]
    explanation: DecisionExplanation
    contract: ReplyContract
    grounding_facts: tuple[str, ...] = ()
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ReplyResult:
    text: str | None
    verified: bool
    fallback_used: bool
    reason: str | None
