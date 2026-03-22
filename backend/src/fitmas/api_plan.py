from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import plan_actions, repository as repo
from fitmas.db import get_db
from fitmas.models import MoveSessionPayload, ScheduledSession

router = APIRouter()


@router.post("/api/v0/plan/sessions/{session_id}/complete", response_model=ScheduledSession)
def complete_session(session_id: int, db: Session = Depends(get_db)) -> ScheduledSession:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    session = plan_actions.complete_session(db, user=user, session_id=session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")
    return repo.to_pydantic_scheduled_session(session)


@router.post("/api/v0/plan/sessions/{session_id}/skip", response_model=ScheduledSession)
def skip_session(session_id: int, db: Session = Depends(get_db)) -> ScheduledSession:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    session = plan_actions.skip_session(db, user=user, session_id=session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")
    return repo.to_pydantic_scheduled_session(session)


@router.post("/api/v0/plan/sessions/{session_id}/move", response_model=ScheduledSession)
def move_session(
    session_id: int,
    payload: MoveSessionPayload | None = None,
    db: Session = Depends(get_db),
) -> ScheduledSession:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    target_date = None
    if payload and payload.target_date:
        try:
            target_date = date.fromisoformat(payload.target_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid target_date") from exc
    session = plan_actions.move_session(db, user=user, session_id=session_id, target_date=target_date)
    if session is None:
        raise HTTPException(status_code=404, detail="Scheduled session not found")
    return repo.to_pydantic_scheduled_session(session)
