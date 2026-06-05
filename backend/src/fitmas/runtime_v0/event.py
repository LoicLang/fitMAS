from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

@dataclass(frozen=True)
class InputEvent:
    id: str
    user_id: int
    source: Literal["telegram", "app", "scheduler", "test"]
    type: Literal[
        "user_message",
        "heartbeat_tick",
        "activity_imported",
        "session_missed_detected",
    ]
    text: str | None
    payload: dict[str, Any]
    occurred_at: datetime
