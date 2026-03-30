from __future__ import annotations

from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s, strava
from fitmas.db import get_db
from fitmas.models import (
    Activity,
    ChangeNote,
    DayId,
    Profile,
    RecentSportActivity,
    ScheduledSession,
    TodayFitness,
    TodayView,
    UserFact,
    UserPattern,
    WatchItem,
    WeeklyPlan,
)
from fitmas.session_metadata import compute_load_band
from fitmas.training_load import compute_ctl_atl_tsb
from fitmas.time_context import get_local_now

router = APIRouter()


def _build_today_view(
    db: Session,
    *,
    user: s.User,
    session: s.ScheduledSession,
) -> TodayView:
    _, day_row = repo.get_current_week_day_plan_for_session(db, user=user, session=session)
    if day_row is not None:
        change_notes = [ChangeNote(title=note.title, detail=note.detail) for note in day_row.change_notes]
        watch_items = [WatchItem(title=item.title, detail=item.detail) for item in day_row.watch_items]
    else:
        change_notes = []
        watch_items = []
    fitness = _build_today_fitness(db, user=user)
    recent_activity = _build_recent_activity(db, user=user, session=session)
    return TodayView(
        scheduled_session_id=session.id,
        scheduled_date=session.scheduled_date.date().isoformat(),
        day=DayId(session.day),
        label=session.label,
        sport_type=session.sport_type,
        session_type=session.session_type,
        session_title=session.session_title,
        session_goal=session.session_goal,
        session_note=session.session_note or "",
        session_description=session.session_description or "",
        duration_min=session.duration_min,
        intensity=session.intensity,
        load_band=compute_load_band(
            sport_type=session.sport_type,
            session_type=session.session_type,
            intensity=session.intensity,
            load_score=session.load_score,
        ),
        priority=session.priority,
        nutrition_focus=session.nutrition_focus or "",
        completion_status=session.completion_status,
        change_notes=change_notes,
        watch_items=watch_items,
        fitness=fitness,
        recent_activity=recent_activity,
    )


def _build_today_fitness(db: Session, *, user: s.User) -> TodayFitness:
    activities = repo.get_activities(db, user.id, limit=500)
    local_today = get_local_now(user.timezone).date()
    load = compute_ctl_atl_tsb(activities, as_of_date=local_today)
    tsb = float(load["tsb"])
    freshness = "stable"
    if tsb >= 5:
        freshness = "frais"
    elif tsb < -10:
        freshness = "fatigué"
    return TodayFitness(
        ctl=float(load["ctl"]),
        atl=float(load["atl"]),
        tsb=tsb,
        freshness=freshness,
    )


def _build_recent_activity(
    db: Session,
    *,
    user: s.User,
    session: s.ScheduledSession,
) -> RecentSportActivity | None:
    if session.sport_type == "rest":
        return None
    session_day_end = datetime.combine(session.scheduled_date.date(), time.min) + timedelta(days=1)
    activity = repo.get_recent_activity_for_sport(
        db,
        user.id,
        sport_type=session.sport_type,
        before=session_day_end,
    )
    if activity is None:
        return None
    return RecentSportActivity(
        id=activity.id,
        title=activity.title,
        started_at=activity.started_at.isoformat() if activity.started_at else None,
        duration_min=activity.duration_min,
        distance_m=activity.distance_m,
        avg_hr=activity.avg_hr,
        avg_speed=activity.avg_speed,
        tss=activity.tss,
    )


@router.get("/api/v0/profile", response_model=Profile)
def get_profile(db: Session = Depends(get_db)) -> Profile:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    return repo.to_pydantic_profile(user)


@router.get("/api/v0/week", response_model=WeeklyPlan)
def get_week(db: Session = Depends(get_db)) -> WeeklyPlan:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    plan = repo.get_active_plan(db, user.id)
    return repo.to_pydantic_plan(plan)


@router.get("/api/v0/today", response_model=TodayView)
def get_today(db: Session = Depends(get_db)) -> TodayView:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    if session is None:
        raise HTTPException(status_code=404, detail="No scheduled session for today")
    return _build_today_view(db, user=user, session=session)


@router.get("/api/v0/today/session/{session_id}", response_model=TodayView)
def get_today_session(session_id: int, db: Session = Depends(get_db)) -> TodayView:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")
    return _build_today_view(db, user=user, session=session)


@router.get("/api/v0/today/{day}", response_model=TodayView)
def get_today_by_day(day: DayId, db: Session = Depends(get_db)) -> TodayView:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    # Prefer ScheduledSession (source of truth for dated planning)
    matching_session = next(
        (
            session
            for session in repo.get_scheduled_sessions(db, user.id, limit=21)
            if session.day == day.value
        ),
        None,
    )
    if matching_session is not None:
        return _build_today_view(db, user=user, session=matching_session)
    # Fall back to legacy DayPlan
    plan = repo.get_active_plan(db, user.id)
    day_row = repo.get_day_plan(db, plan.id, day.value)
    if day_row is None:
        raise HTTPException(status_code=404, detail=f"Day {day.value} not found in plan")
    d = repo.to_pydantic_day(day_row)
    return TodayView(
        scheduled_session_id=0,
        scheduled_date="",
        day=d.day,
        label=d.label,
        sport_type=d.sport_type,
        session_type=d.session_type,
        session_title=d.session_title,
        session_goal=d.session_goal,
        session_note=d.session_note,
        session_description=d.session_description,
        duration_min=d.duration_min,
        intensity=d.intensity,
        load_band=d.load_band,
        priority=d.priority,
        nutrition_focus=d.nutrition_focus,
        completion_status=d.completion_status,
        change_notes=d.change_notes,
        watch_items=d.watch_items,
    )


@router.get("/api/v0/messages")
def get_messages(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        return {"messages": []}
    msgs = repo.get_messages(db, user.id)
    return {"messages": [repo.to_pydantic_message(m).model_dump() for m in msgs]}


@router.get("/api/v0/facts", response_model=list[UserFact])
def get_facts(db: Session = Depends(get_db)) -> list[UserFact]:
    user = repo.get_user_optional(db)
    if user is None:
        return []
    facts = repo.get_active_memory_items(db, user.id, profile_limit=24, working_limit=24, total_limit=32)
    return [repo.to_pydantic_fact(fact) for fact in facts]


@router.get("/api/v0/patterns", response_model=list[UserPattern])
def get_patterns(db: Session = Depends(get_db)) -> list[UserPattern]:
    user = repo.get_user_optional(db)
    if user is None:
        return []
    patterns = repo.get_active_patterns(db, user.id, limit=12)
    return [repo.to_pydantic_pattern(pattern) for pattern in patterns]


@router.get("/api/v0/activities", response_model=list[Activity])
def get_activities(db: Session = Depends(get_db)) -> list[Activity]:
    user = repo.get_user_optional(db)
    if user is None:
        return []
    activities = repo.get_activities(db, user.id)
    return [repo.to_pydantic_activity(activity) for activity in activities]


@router.get("/api/v0/activities/{activity_id}", response_model=Activity)
def get_activity(activity_id: int, db: Session = Depends(get_db)) -> Activity:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No user")
    activity = db.query(s.Activity).filter(s.Activity.id == activity_id, s.Activity.user_id == user.id).first()
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return repo.to_pydantic_activity(activity)


@router.get("/api/v0/timeline", response_model=list[ScheduledSession])
def get_timeline(limit: int = 42, db: Session = Depends(get_db)) -> list[ScheduledSession]:
    user = repo.get_user_optional(db)
    if user is None:
        return []
    sessions = repo.get_scheduled_sessions(db, user.id, limit=max(1, min(limit, 84)))
    return [repo.to_pydantic_scheduled_session(session) for session in sessions]


@router.get("/api/v0/strava/status")
def get_strava_status(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        return {"configured": strava.is_configured(), "connected": False, "last_sync_at": None}
    connection = repo.get_strava_connection(db, user.id)
    return {
        "configured": strava.is_configured(),
        "connected": connection is not None,
        "last_sync_at": connection.last_sync_at.isoformat() if connection and connection.last_sync_at else None,
        "scopes": connection.scopes if connection else "",
    }
