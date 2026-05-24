from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ConversationState:
    last_unresolved_intent: dict[str, Any] | None
    last_execution_event_id: int | None
    last_pending_id: int | None
    last_user_turn_id: str | None
    expires_at: datetime | None

    def active_at(self, now: datetime) -> "ConversationState":
        if self.expires_at is not None and self.expires_at <= now:
            return ConversationState(
                last_unresolved_intent=None,
                last_execution_event_id=self.last_execution_event_id,
                last_pending_id=self.last_pending_id,
                last_user_turn_id=self.last_user_turn_id,
                expires_at=self.expires_at,
            )
        return self
