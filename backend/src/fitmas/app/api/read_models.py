from __future__ import annotations

from pydantic import BaseModel

from fitmas.domain.planning.view_models import (
    ChangeNote,
    DayId,
    DayPlan as RuntimeDay,
    WatchItem,
    WeeklyPlan as RuntimeWeek,
)


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
    session_note: str = ""
    session_description: str = ""
    duration_min: int | None = None
    intensity: str = "easy"
    load_band: str = "easy"
    priority: str
    nutrition_focus: str
    completion_status: str = "planned"
    change_notes: list[ChangeNote]
    watch_items: list[WatchItem]
    fitness: TodayFitness | None = None
    recent_activity: RecentSportActivity | None = None


__all__ = [
    "RecentSportActivity",
    "RuntimeDay",
    "RuntimeWeek",
    "TodayFitness",
    "TodayView",
]
