from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class MessageRole(StrEnum):
    AGENT = "agent"
    USER = "user"


class DayId(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class ChangeNote(BaseModel):
    title: str
    detail: str


class WatchItem(BaseModel):
    title: str
    detail: str


class DayPlan(BaseModel):
    day: DayId
    label: str
    session_title: str
    session_goal: str
    session_note: str
    priority: str
    nutrition_focus: str
    change_notes: list[ChangeNote] = Field(default_factory=list)
    watch_items: list[WatchItem] = Field(default_factory=list)
    flexibility: str


class WeeklyPlan(BaseModel):
    intention: str
    summary: str
    days: list[DayPlan]


class Profile(BaseModel):
    name: str
    age: int
    objective: str
    coaching_style: str
    constraints: list[str]
    preferences: list[str]
    integrations: list[str]


class TodayView(BaseModel):
    day: DayId
    session_title: str
    session_goal: str
    priority: str
    nutrition_focus: str
    change_notes: list[ChangeNote]
    watch_items: list[WatchItem]


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
