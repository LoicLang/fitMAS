from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


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
    sport_type: str = "running"
    session_type: str = "easy"
    session_title: str
    session_goal: str
    session_note: str
    session_description: str = ""
    duration_min: int | None = None
    intensity: str = "easy"
    load_score: int = 1
    load_band: str = "easy"
    priority: str
    nutrition_focus: str
    change_notes: list[ChangeNote] = Field(default_factory=list)
    watch_items: list[WatchItem] = Field(default_factory=list)
    flexibility: str
    completion_status: str = "planned"


class WeeklyPlan(BaseModel):
    runtime_role: str = "template_compat"
    intention: str
    summary: str
    mesocycle_week: int = 1
    mesocycle_number: int = 1
    cycle_length: int = 4
    total_weeks: int = 1
    is_deload: bool = False
    week_label: str = ""
    days: list[DayPlan]


class ScheduledSession(BaseModel):
    id: int
    day: DayId
    label: str
    scheduled_date: str
    sport_type: str = "running"
    session_type: str = "easy"
    session_title: str
    session_goal: str
    session_note: str = ""
    session_description: str = ""
    duration_min: int | None = None
    intensity: str = "easy"
    load_score: int = 1
    load_band: str = "easy"
    priority: str
    nutrition_focus: str = ""
    flexibility: str = "stable"
    completion_status: str = "planned"
    linked_activity_id: int | None = None


class WorkoutContentView(BaseModel):
    objective: str
    rationale: str
    execution: list[str]
    coach_cue: str
    nutrition_note: str
