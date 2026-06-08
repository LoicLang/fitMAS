from __future__ import annotations

from pydantic import BaseModel


class IncomingMessage(BaseModel):
    text: str
    client_message_key: str | None = None
    source: str | None = None


class MoveSessionPayload(BaseModel):
    target_date: str | None = None


class OnboardPayload(BaseModel):
    name: str
    primary_objective: str
    sports: list[str]
    weekly_structure_notes: str
    constraints: list[str]
    preferences: list[str]
    goal_context: str = ""
    current_state_notes: str = ""
    coach_name: str | None = None
    coach_preset: str = "direct"
    coach_style: str = ""
    coach_relationship: str = ""
    coach_do: str = ""
    coach_dont: str = ""
    coach_soul: str = ""
    coach_adjustment_notes: str = ""
    timezone: str = ""
    telegram_chat_id: int | None = None


class OnboardPreviewPayload(OnboardPayload):
    pass


class ManualActivityPayload(BaseModel):
    sport_type: str
    title: str | None = None
    duration_min: int | None = None
    distance_m: float | None = None
    elevation_m: float | None = None
    perceived_load: int | None = None
    note: str = ""
    started_at: str | None = None
