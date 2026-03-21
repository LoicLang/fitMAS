from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s, strava
from fitmas.db import get_db
from fitmas.models import Activity, DayId, Profile, TodayView, UserFact, WeeklyPlan

router = APIRouter()


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


@router.get("/api/v0/today/{day}", response_model=TodayView)
def get_today(day: DayId, db: Session = Depends(get_db)) -> TodayView:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    plan = repo.get_active_plan(db, user.id)
    day_row = repo.get_day_plan(db, plan.id, day.value)
    if day_row is None:
        raise HTTPException(status_code=404, detail=f"Day {day.value} not found in plan")
    d = repo.to_pydantic_day(day_row)
    return TodayView(
        day=d.day,
        sport_type=d.sport_type,
        session_type=d.session_type,
        session_title=d.session_title,
        session_goal=d.session_goal,
        session_description=d.session_description,
        duration_min=d.duration_min,
        intensity=d.intensity,
        priority=d.priority,
        nutrition_focus=d.nutrition_focus,
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
    facts = repo.get_active_facts(db, user.id)
    return [repo.to_pydantic_fact(fact) for fact in facts]


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
