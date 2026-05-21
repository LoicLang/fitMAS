from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from fitmas import repository as repo, strava
from fitmas.activities import infer_activity_title, match_activity_to_day, normalize_activity_sport
from fitmas.app.api.payloads import ManualActivityPayload
from fitmas.app.api.support import parse_optional_datetime, public_base_url
from fitmas.db import get_db
from fitmas.models import Activity
from fitmas.domain.planning.patch_mutation_service import complete_session_from_activity_for_user
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
    imported = strava.import_recent_activities(
        db,
        user_id=user.id,
        connection=connection,
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
    scheduled_sessions = repo.get_scheduled_sessions(db, user.id, limit=84)
    matched_day, match_reason = match_activity_to_day(
        sport_type=sport_type,
        started_at=started_at,
        duration_min=payload.duration_min,
        scheduled_sessions=scheduled_sessions,
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
        logger.info("Matched %s to manual activity: %s", matched_day, title)
    if scheduled_session:
        complete_session_from_activity_for_user(
            db,
            user=user,
            session_id=scheduled_session.id,
            plan_id=None,
            matched_day=matched_day,
            source="manual_activity",
        )

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
    imported = strava.import_recent_activities(
        db,
        user_id=user.id,
        connection=connection,
    )
    logger.info("Strava sync: %d new activities imported", imported)
    return {"synced": True, "imported": imported}
