from __future__ import annotations

from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas.legacy.core import orm as s
from fitmas.legacy.integrations import strava
from fitmas.legacy.integrations import repository as integration_repo
from fitmas.legacy.app.api.read_models import RecentSportActivity, RuntimeDay, RuntimeWeek, TodayFitness, TodayView
from fitmas.legacy.core.db import get_db
from fitmas.legacy.domain.athlete.view_models import Profile
from fitmas.legacy.domain.execution.view_models import Activity
from fitmas.legacy.domain.memory.view_models import UserFact, UserPattern
from fitmas.legacy.domain.planning.view_models import ChangeNote, DayId, ScheduledSession, WatchItem
from fitmas.legacy.domain.planning.models import compute_load_band
from fitmas.legacy.domain.athlete.training_load import compute_ctl_atl_tsb
from fitmas.legacy.core.time_context import current_week_dates, get_local_now
from fitmas.legacy.domain.athlete import repository as athlete_repo
from fitmas.legacy.domain.coaching import repo_conversation
from fitmas.legacy.domain.execution import repository as execution_repo
from fitmas.legacy.domain.memory import repository as memory_repo
from fitmas.legacy.domain.planning import repository as planning_repo

router = APIRouter()


def _build_today_view(
    db: Session,
    *,
    user: s.User,
    session: s.ScheduledSession,
) -> TodayView:
    change_notes: list[ChangeNote] = []
    watch_items: list[WatchItem] = []
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


def _build_week_day_from_scheduled_session(session: s.ScheduledSession) -> RuntimeDay:
    return RuntimeDay(
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
        load_score=session.load_score,
        load_band=compute_load_band(
            sport_type=session.sport_type,
            session_type=session.session_type,
            intensity=session.intensity,
            load_score=session.load_score,
        ),
        priority=session.priority,
        nutrition_focus=session.nutrition_focus or "",
        flexibility=session.flexibility,
        completion_status=session.completion_status,
        change_notes=[],
        watch_items=[],
    )


def _build_runtime_week_plan(sessions: list[s.ScheduledSession], *, week_label: str = "") -> RuntimeWeek:
    return RuntimeWeek(
        runtime_role="scheduled_runtime",
        intention="",
        summary="",
        mesocycle_week=1,
        mesocycle_number=1,
        cycle_length=4,
        total_weeks=1,
        is_deload=False,
        week_label=week_label,
        days=[_build_week_day_from_scheduled_session(session) for session in sessions],
    )


def _build_today_fitness(db: Session, *, user: s.User) -> TodayFitness:
    activities = execution_repo.get_activities(db, user.id, limit=500)
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
    activity = execution_repo.get_recent_activity_for_sport(
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
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    return athlete_repo.to_pydantic_profile(user)


@router.get("/api/v0/week", response_model=RuntimeWeek)
def get_week(db: Session = Depends(get_db)) -> RuntimeWeek:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    week_dates = current_week_dates(user.timezone)
    sessions = planning_repo.get_scheduled_sessions_between_dates(
        db,
        user.id,
        start_date=week_dates["monday"],
        end_date=week_dates["sunday"],
        limit=32,
    )
    week_label = f"{week_dates['monday'].isoformat()} / {week_dates['sunday'].isoformat()}"
    return _build_runtime_week_plan(sessions, week_label=week_label)


@router.get("/api/v0/today", response_model=TodayView)
def get_today(db: Session = Depends(get_db)) -> TodayView:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    session = planning_repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    if session is None:
        raise HTTPException(status_code=404, detail="No scheduled session for today")
    return _build_today_view(db, user=user, session=session)


@router.get("/api/v0/today/session/{session_id}", response_model=TodayView)
def get_today_session(session_id: int, db: Session = Depends(get_db)) -> TodayView:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    session = planning_repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")
    return _build_today_view(db, user=user, session=session)


@router.get("/api/v0/today/{day}", response_model=TodayView)
def get_today_by_day(day: DayId, db: Session = Depends(get_db)) -> TodayView:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    matching_session = next(
        (
            session
            for session in planning_repo.get_scheduled_sessions(db, user.id, limit=21)
            if session.day == day.value
        ),
        None,
    )
    if matching_session is not None:
        return _build_today_view(db, user=user, session=matching_session)
    raise HTTPException(status_code=404, detail=f"No scheduled session found for {day.value}")


@router.get("/api/v0/messages")
def get_messages(db: Session = Depends(get_db)) -> dict:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        return {"messages": []}
    msgs = repo_conversation.get_messages(db, user.id)
    return {"messages": [repo_conversation.to_pydantic_message(m).model_dump() for m in msgs]}


@router.get("/api/v0/facts", response_model=list[UserFact])
def get_facts(db: Session = Depends(get_db)) -> list[UserFact]:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        return []
    facts = memory_repo.get_active_memory_items(db, user.id, profile_limit=24, working_limit=24, total_limit=32)
    return [memory_repo.to_pydantic_fact(fact) for fact in facts]


@router.get("/api/v0/patterns", response_model=list[UserPattern])
def get_patterns(db: Session = Depends(get_db)) -> list[UserPattern]:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        return []
    patterns = memory_repo.get_active_patterns(db, user.id, limit=12)
    return [memory_repo.to_pydantic_pattern(pattern) for pattern in patterns]


@router.get("/api/v0/activities", response_model=list[Activity])
def get_activities(db: Session = Depends(get_db)) -> list[Activity]:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        return []
    activities = execution_repo.get_activities(db, user.id)
    return [execution_repo.to_pydantic_activity(activity) for activity in activities]


@router.get("/api/v0/activities/{activity_id}", response_model=Activity)
def get_activity(activity_id: int, db: Session = Depends(get_db)) -> Activity:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No user")
    activity = db.query(s.Activity).filter(s.Activity.id == activity_id, s.Activity.user_id == user.id).first()
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return execution_repo.to_pydantic_activity(activity)


@router.get("/api/v0/timeline", response_model=list[ScheduledSession])
def get_timeline(limit: int = 42, db: Session = Depends(get_db)) -> list[ScheduledSession]:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        return []
    sessions = planning_repo.get_scheduled_sessions(db, user.id, limit=max(1, min(limit, 84)))
    return [planning_repo.to_pydantic_scheduled_session(session) for session in sessions]


@router.get("/api/v0/strava/status")
def get_strava_status(db: Session = Depends(get_db)) -> dict:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        return {"configured": strava.is_configured(), "connected": False, "last_sync_at": None}
    connection = integration_repo.get_strava_connection(db, user.id)
    return {
        "configured": strava.is_configured(),
        "connected": connection is not None,
        "last_sync_at": connection.last_sync_at.isoformat() if connection and connection.last_sync_at else None,
        "scopes": connection.scopes if connection else "",
    }
