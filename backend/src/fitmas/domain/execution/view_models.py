from __future__ import annotations

from pydantic import BaseModel


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
