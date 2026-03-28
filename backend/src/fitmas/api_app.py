from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s, strava
from fitmas.api_read import _build_recent_activity, _build_today_fitness, _build_today_view
from fitmas.app_views import build_app_calendar, build_app_evolution, build_app_overview, build_session_detail
from fitmas.db import get_db
from fitmas.performance_overview import build_performance_overview
from fitmas.performance_stats import build_training_load_stats
from fitmas.time_context import get_local_now

router = APIRouter()


@router.get("/api/v0/app/overview")
def get_app_overview(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=84)
    activities = repo.get_activities(db, user.id, limit=500)
    planning_decision = repo.get_latest_planning_decision_record(db, user.id)
    today_session = repo.get_today_scheduled_session(db, user.id, timezone_name=user.timezone)
    today_view = _build_today_view(db, user=user, session=today_session).model_dump() if today_session is not None else None
    performance_overview = build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        week_plan=repo.to_pydantic_plan(repo.get_active_plan(db, user.id)),
        planning_decision=planning_decision,
    )
    strava_status = {
        "configured": strava.is_configured(),
        "connected": repo.get_strava_connection(db, user.id) is not None,
        "last_sync_at": None,
    }
    connection = repo.get_strava_connection(db, user.id)
    if connection and connection.last_sync_at:
        strava_status["last_sync_at"] = connection.last_sync_at.isoformat()

    return build_app_overview(
        today_date=get_local_now(user.timezone).date(),
        profile=repo.to_pydantic_profile(user),
        strava_status=strava_status,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        performance_overview=performance_overview,
        today_view=today_view,
    )


@router.get("/api/v0/app/calendar")
def get_app_calendar(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    today_date = get_local_now(user.timezone).date()
    month_start = date.fromisoformat(f"{month or today_date.isoformat()[:7]}-01")
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=120)
    activities = repo.get_activities(db, user.id, limit=500)
    planning_decision = repo.get_latest_planning_decision_record(db, user.id)
    performance_overview = build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        week_plan=repo.to_pydantic_plan(repo.get_active_plan(db, user.id)),
        planning_decision=planning_decision,
    )

    return build_app_calendar(
        today_date=today_date,
        month_start=month_start,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        performance_overview=performance_overview,
    )


@router.get("/api/v0/app/evolution")
def get_app_evolution(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    today_date = get_local_now(user.timezone).date()
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=120)
    activities = repo.get_activities(db, user.id, limit=500)
    planning_decision = repo.get_latest_planning_decision_record(db, user.id)
    performance_overview = build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        week_plan=repo.to_pydantic_plan(repo.get_active_plan(db, user.id)),
        planning_decision=planning_decision,
    )
    training_load = build_training_load_stats(activities, as_of_date=today_date, weeks=16)
    return build_app_evolution(
        today_date=today_date,
        scheduled_sessions=scheduled_sessions,
        activities=activities,
        performance_overview=performance_overview,
        training_load=training_load,
    )


@router.get("/api/v0/sessions/{session_id}")
def get_session_detail(session_id: int, db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    session = repo.get_scheduled_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")

    _, day_row = repo.get_current_week_day_plan_for_session(db, user=user, session=session)
    linked_activity = next((activity for activity in session.activities if activity.sport_type == session.sport_type), None)
    recent_activity = _build_recent_activity(db, user=user, session=session)
    change_notes = [{"title": note.title, "detail": note.detail} for note in (day_row.change_notes if day_row else [])]
    watch_items = [{"title": item.title, "detail": item.detail} for item in (day_row.watch_items if day_row else [])]

    return build_session_detail(
        today_date=get_local_now(user.timezone).date(),
        session=session,
        linked_activity=repo.to_pydantic_activity(linked_activity).model_dump() if linked_activity is not None else None,
        fitness=_build_today_fitness(db, user=user).model_dump(),
        recent_activity=recent_activity.model_dump() if recent_activity is not None else None,
        change_notes=change_notes,
        watch_items=watch_items,
    )
