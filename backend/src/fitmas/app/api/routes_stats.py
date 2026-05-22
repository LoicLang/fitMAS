from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.db import get_db
from fitmas.domain.athlete.performance_overview import build_performance_overview
from fitmas.domain.athlete.performance_stats import build_records_stats, build_training_load_stats, build_volume_stats

router = APIRouter()


@router.get("/api/v0/stats/training-load")
def get_training_load_stats(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    activities = repo.get_activities(db, user.id, limit=500)
    return build_training_load_stats(activities)


@router.get("/api/v0/stats/volume")
def get_volume_stats(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    activities = repo.get_activities(db, user.id, limit=500)
    return build_volume_stats(activities)


@router.get("/api/v0/stats/records")
def get_records_stats(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    activities = repo.get_activities(db, user.id, limit=500)
    return build_records_stats(activities)


@router.get("/api/v0/stats/performance-overview")
def get_performance_overview(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    activities = repo.get_activities(db, user.id, limit=500)
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=84)
    planning_decision = repo.get_latest_planning_decision_record(db, user.id)
    return build_performance_overview(
        user_id=user.id,
        timezone_name=user.timezone,
        activities=activities,
        scheduled_sessions=scheduled_sessions,
        planning_decision=planning_decision,
    )
