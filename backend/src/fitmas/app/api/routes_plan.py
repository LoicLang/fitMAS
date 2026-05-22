from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas.core.db import get_db
from fitmas.app.api.payloads import MoveSessionPayload
from fitmas.domain.planning.view_models import ScheduledSession
from fitmas.domain.planning.patch_mutation_service import complete_session_for_user, move_session_for_user, skip_session_for_user
from fitmas.domain.athlete import repository as athlete_repo
from fitmas.domain.planning import repository as planning_repo

router = APIRouter()


@router.post("/api/v0/plan/sessions/{session_id}/complete", response_model=ScheduledSession)
def complete_session(session_id: int, db: Session = Depends(get_db)) -> ScheduledSession:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    result = complete_session_for_user(db, user=user, session_id=session_id, source="app")
    if result is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")
    return planning_repo.to_pydantic_scheduled_session(result.session)


@router.post("/api/v0/plan/sessions/{session_id}/skip", response_model=ScheduledSession)
def skip_session(session_id: int, db: Session = Depends(get_db)) -> ScheduledSession:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    result = skip_session_for_user(db, user=user, session_id=session_id, source="app")
    if result is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")
    return planning_repo.to_pydantic_scheduled_session(result.session)


@router.post("/api/v0/plan/sessions/{session_id}/move", response_model=ScheduledSession)
def move_session(
    session_id: int,
    payload: MoveSessionPayload | None = None,
    db: Session = Depends(get_db),
) -> ScheduledSession:
    user = athlete_repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    target_date = None
    if payload and payload.target_date:
        try:
            target_date = date.fromisoformat(payload.target_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid target_date") from exc
    result = move_session_for_user(db, user=user, session_id=session_id, target_date=target_date, source="app")
    if result is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")
    return planning_repo.to_pydantic_scheduled_session(result.session)
