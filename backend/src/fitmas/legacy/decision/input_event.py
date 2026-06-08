from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Mapping


InputEventSource = Literal["telegram", "app", "scheduler", "strava", "ops"]
InputEventType = Literal[
    "user_message",
    "app_action",
    "activity_synced",
    "missed_session_detected",
    "heartbeat_tick",
    "weekly_review_tick",
    "pending_timeout",
]


@dataclass(frozen=True, slots=True)
class InputEvent:
    id: str
    user_id: int
    source: InputEventSource
    type: InputEventType
    text: str | None
    payload: Mapping[str, Any]
    occurred_at: datetime
