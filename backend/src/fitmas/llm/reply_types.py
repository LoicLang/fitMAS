from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


RequestTextFn = Callable[..., str | None]


@dataclass(frozen=True, slots=True)
class BlockedEvent:
    command: str
    reason: str | None = None
    suggested_fix: str | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class FinalReplyContext:
    user_text: str = ""
    original_llm_reply: str = ""
    committed_events: tuple[str, ...] = ()
    blocked_events: tuple[BlockedEvent, ...] = ()
    pending_summary: str | None = None
    memory_actions_applied: tuple[str, ...] = ()
    execution_actions_applied: tuple[str, ...] = ()
    allowed_to_claim_mutation: bool = False
    pipeline: str = "conversation"
    pipeline_capability: str = "can_confirm"
    extra_facts: tuple[str, ...] = field(default_factory=tuple)
