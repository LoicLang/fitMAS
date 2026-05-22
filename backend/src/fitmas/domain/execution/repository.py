from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from fitmas.core import orm as s
from fitmas.domain.execution.view_models import Activity as ActivityDTO


def to_pydantic_activity(activity: s.Activity) -> ActivityDTO:
    return ActivityDTO(
        id=activity.id,
        source=activity.source,
        external_id=activity.external_id,
        scheduled_session_id=activity.scheduled_session_id,
        sport_type=activity.sport_type,
        title=activity.title,
        duration_min=activity.duration_min,
        distance_m=activity.distance_m,
        elevation_m=activity.elevation_m,
        perceived_load=activity.perceived_load,
        note=activity.note,
        started_at=activity.started_at.isoformat() if activity.started_at else None,
        matched_day=activity.matched_day,
        match_reason=activity.match_reason,
        avg_hr=activity.avg_hr,
        max_hr=activity.max_hr,
        avg_speed=activity.avg_speed,
        calories=activity.calories,
        suffer_score=activity.suffer_score,
        tss=activity.tss,
        map_polyline=activity.map_polyline,
        start_latlng=activity.start_latlng,
    )


def get_activities(db: Session, user_id: int, limit: int = 30) -> list[s.Activity]:
    return (
        db.query(s.Activity)
        .filter(s.Activity.user_id == user_id)
        .order_by(s.Activity.started_at.is_(None), s.Activity.started_at.desc(), s.Activity.created_at.desc())
        .limit(limit)
        .all()
    )


def get_recent_activity_for_sport(
    db: Session,
    user_id: int,
    *,
    sport_type: str,
    before: datetime | None = None,
) -> s.Activity | None:
    query = (
        db.query(s.Activity)
        .filter(s.Activity.user_id == user_id, s.Activity.sport_type == sport_type)
    )
    if before is not None:
        query = query.filter(s.Activity.started_at.is_not(None), s.Activity.started_at < before)
    return (
        query
        .order_by(s.Activity.started_at.is_(None), s.Activity.started_at.desc(), s.Activity.created_at.desc())
        .first()
    )


def get_activity_by_external_id(db: Session, user_id: int, external_id: str) -> s.Activity | None:
    return (
        db.query(s.Activity)
        .filter(s.Activity.user_id == user_id, s.Activity.external_id == external_id)
        .first()
    )


def add_activity(
    db: Session,
    *,
    user_id: int,
    source: str,
    external_id: str | None = None,
    scheduled_session_id: int | None = None,
    sport_type: str,
    title: str,
    duration_min: int | None,
    distance_m: float | None,
    elevation_m: float | None,
    perceived_load: int | None,
    note: str,
    started_at,
    matched_day: str | None,
    match_reason: str,
    avg_hr: float | None = None,
    max_hr: float | None = None,
    avg_speed: float | None = None,
    calories: float | None = None,
    suffer_score: int | None = None,
    tss: float | None = None,
    map_polyline: str | None = None,
    start_latlng: str | None = None,
) -> s.Activity:
    activity = s.Activity(
        user_id=user_id,
        source=source,
        external_id=external_id,
        scheduled_session_id=scheduled_session_id,
        sport_type=sport_type,
        title=title,
        duration_min=duration_min,
        distance_m=distance_m,
        elevation_m=elevation_m,
        perceived_load=perceived_load,
        note=note,
        started_at=started_at,
        matched_day=matched_day,
        match_reason=match_reason,
        avg_hr=avg_hr,
        max_hr=max_hr,
        avg_speed=avg_speed,
        calories=calories,
        suffer_score=suffer_score,
        tss=tss,
        map_polyline=map_polyline,
        start_latlng=start_latlng,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity
