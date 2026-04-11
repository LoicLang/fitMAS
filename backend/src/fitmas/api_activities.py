from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from fitmas import repository as repo, strava
from fitmas.activities import infer_activity_title, match_activity_to_day, normalize_activity_sport
from fitmas.api_payloads import ManualActivityPayload
from fitmas.api_support import parse_optional_datetime, public_base_url
from fitmas.db import get_db
from fitmas.models import Activity
from fitmas.plan_mutation_service import mark_day_completed_for_user, mark_session_completed_for_user
from fitmas.training_load import estimate_tss

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v0/strava/auth")
def start_strava_auth(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    if not strava.is_configured():
        raise HTTPException(status_code=503, detail="Strava is not configured")
    callback_url = public_base_url(request) + "/api/v0/strava/callback"
    url = strava.build_auth_url(callback_url=callback_url, state=str(user.id))
    return RedirectResponse(url=url, status_code=302)


@router.get("/api/v0/strava/callback")
def finish_strava_auth(code: str, state: str, request: Request, db: Session = Depends(get_db)):
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    if str(user.id) != state:
        raise HTTPException(status_code=400, detail="Invalid Strava state")
    if not strava.is_configured():
        raise HTTPException(status_code=503, detail="Strava is not configured")

    token_payload = strava.exchange_code_for_token(code=code)
    connection = strava.store_connection_from_token_payload(db, user_id=user.id, payload=token_payload)
    plan = repo.get_active_plan(db, user.id)
    week_days = repo.to_pydantic_plan(plan).days
    imported = strava.import_recent_activities(
        db,
        user_id=user.id,
        connection=connection,
        week_days=week_days,
        plan_id=plan.id,
        plan_created_at=plan.created_at,
    )
    logger.info("Strava OAuth done: %d activities imported for user %s", imported, user.id)
    return RedirectResponse(url=f"{public_base_url(request)}/?strava=connected&imported={imported}", status_code=302)


@router.post("/api/v0/activities/manual", response_model=Activity)
def create_manual_activity(payload: ManualActivityPayload, db: Session = Depends(get_db)) -> Activity:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    sport_type = normalize_activity_sport(payload.sport_type)
    title = (payload.title or "").strip() or infer_activity_title(sport_type, payload.duration_min, payload.note)
    started_at = parse_optional_datetime(payload.started_at)
    plan = repo.get_active_plan(db, user.id)
    week_days = repo.to_pydantic_plan(plan).days
    matched_day, match_reason = match_activity_to_day(
        sport_type=sport_type,
        started_at=started_at,
        duration_min=payload.duration_min,
        week_days=week_days,
        plan_created_at=plan.created_at,
    )
    estimated_tss = estimate_tss(
        {
            "sport_type": sport_type,
            "duration_min": payload.duration_min,
            "perceived_load": payload.perceived_load,
            "avg_hr": None,
        },
        user,
    )
    scheduled_session = repo.find_scheduled_session_for_activity(
        db,
        user_id=user.id,
        sport_type=sport_type,
        started_at=started_at,
        timezone_name=user.timezone,
    )

    activity = repo.add_activity(
        db,
        user_id=user.id,
        source="manual",
        scheduled_session_id=scheduled_session.id if scheduled_session else None,
        sport_type=sport_type,
        title=title,
        duration_min=payload.duration_min,
        distance_m=payload.distance_m,
        elevation_m=payload.elevation_m,
        perceived_load=payload.perceived_load,
        note=payload.note.strip(),
        started_at=started_at,
        matched_day=matched_day,
        match_reason=match_reason,
        tss=estimated_tss,
    )

    if matched_day:
        mark_day_completed_for_user(db, plan_id=plan.id, day=matched_day, source="manual_activity")
        logger.info("Marked %s as done (manual activity: %s)", matched_day, title)
    if scheduled_session:
        mark_session_completed_for_user(db, user=user, session_id=scheduled_session.id, source="manual_activity")

    return repo.to_pydantic_activity(activity)


@router.post("/api/v0/strava/sync")
def sync_strava(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    if not strava.is_configured():
        return {"synced": False, "reason": "Strava not configured"}
    connection = repo.get_strava_connection(db, user.id)
    if connection is None:
        return {"synced": False, "reason": "Strava not connected"}
    plan = repo.get_active_plan(db, user.id)
    week_days = repo.to_pydantic_plan(plan).days
    imported = strava.import_recent_activities(
        db,
        user_id=user.id,
        connection=connection,
        week_days=week_days,
        plan_id=plan.id,
        plan_created_at=plan.created_at,
    )
    logger.info("Strava sync: %d new activities imported", imported)
    return {"synced": True, "imported": imported}
