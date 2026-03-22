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
    sport_type: str = "running"
    session_type: str = "easy"
    session_title: str
    session_goal: str
    session_note: str
    session_description: str = ""
    duration_min: int | None = None
    intensity: str = "easy"
    load_score: int = 1
    priority: str
    nutrition_focus: str
    change_notes: list[ChangeNote] = Field(default_factory=list)
    watch_items: list[WatchItem] = Field(default_factory=list)
    flexibility: str
    completion_status: str = "planned"


class WeeklyPlan(BaseModel):
    intention: str
    summary: str
    days: list[DayPlan]


class Profile(BaseModel):
    name: str
    age: int
    objective: str
    coaching_style: str
    primary_objective: str = ""
    weekly_structure_notes: str = ""
    coach_name: str = "FitMAS"
    coach_style: str = "direct"
    coach_relationship: str = ""
    coach_do: str = ""
    coach_dont: str = ""
    coach_soul: str = ""
    onboarding_status: str = "not_started"
    sports: list[str] = Field(default_factory=list)
    constraints: list[str]
    preferences: list[str]
    integrations: list[str]


class TodayFitness(BaseModel):
    ctl: float = 0.0
    atl: float = 0.0
    tsb: float = 0.0
    freshness: str = "stable"


class RecentSportActivity(BaseModel):
    id: int
    title: str
    started_at: str | None = None
    duration_min: int | None = None
    distance_m: float | None = None
    avg_hr: float | None = None
    avg_speed: float | None = None
    tss: float | None = None


class TodayView(BaseModel):
    scheduled_session_id: int
    scheduled_date: str
    day: DayId
    label: str
    sport_type: str = "running"
    session_type: str = "easy"
    session_title: str
    session_goal: str
    session_description: str = ""
    duration_min: int | None = None
    intensity: str = "easy"
    priority: str
    nutrition_focus: str
    completion_status: str = "planned"
    change_notes: list[ChangeNote]
    watch_items: list[WatchItem]
    fitness: TodayFitness | None = None
    recent_activity: RecentSportActivity | None = None


class MoveSessionPayload(BaseModel):
    target_date: str | None = None


class Message(BaseModel):
    role: MessageRole
    text: str


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
    priority: str
    nutrition_focus: str = ""
    flexibility: str = "stable"
    completion_status: str = "planned"
    linked_activity_id: int | None = None


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


class UserFact(BaseModel):
    category: str
    key: str
    value: str
    source: str
    confidence: float
    confirmed: bool
    active: bool


class Activity(BaseModel):
    id: int
    source: str
    external_id: str | None = None
    scheduled_session_id: int | None = None
    sport_type: str
    title: str
    duration_min: int | None = None
    distance_m: float | None = None
    elevation_m: float | None = None
    perceived_load: int | None = None
    note: str = ""
    started_at: str | None = None
    matched_day: str | None = None
    match_reason: str = ""
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_speed: float | None = None
    calories: float | None = None
    suffer_score: int | None = None
    tss: float | None = None
    map_polyline: str | None = None
    start_latlng: str | None = None


class OnboardPreview(BaseModel):
    normalized_sports: list[str]
    coach_preview: list[str]
    recap: str


class OnboardResult(BaseModel):
    recap: str
    week_plan: WeeklyPlan
