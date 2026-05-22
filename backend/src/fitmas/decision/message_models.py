from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from fitmas.domain.planning.view_models import DayId


class MessageRole(StrEnum):
    AGENT = "agent"
    USER = "user"


class Message(BaseModel):
    role: MessageRole
    text: str


class Extraction(BaseModel):
    availability: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    feeling: str | None = None
    confidence: float = 0.5
    needs_clarification: bool = False


class MessageReply(BaseModel):
    user_message: Message
    extraction: Extraction
    assistant_message: Message
    day_updated: DayId | None = None
