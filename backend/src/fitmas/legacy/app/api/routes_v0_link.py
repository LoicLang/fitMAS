"""Manual activity<->session link, V0 store only (FITMAS_APP_SOURCE=v0).

The user explicitly links a completed activity to a planned session in the calendar.
Writes go through the official V0 executor (audited) via the app_actions adapter.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fitmas.legacy.app.api.routes_app import _app_source_is_v0
from fitmas.legacy.app.api.v0_source import v0_db_path, v0_user_id, get_scheduled_sessions
from fitmas.runtime_v0.adapters.app_actions import link_activity_to_session, unlink_activity

router = APIRouter()


class LinkPayload(BaseModel):
    session_id: int


class LinkResult(BaseModel):
    activity_id: int
    session_id: int | None
    session_status: str | None


def _require_v0_user() -> int:
    if not _app_source_is_v0():
        raise HTTPException(status_code=409, detail="Link is only available in V0 app mode")
    user_id = v0_user_id()
    if user_id is None:
        raise HTTPException(status_code=404, detail="No V0 user yet")
    return user_id


def _session_status(session_id: int) -> str | None:
    for s in get_scheduled_sessions():
        if s.id == session_id:
            return s.completion_status
    return None


@router.post("/api/v0/activities/{activity_id}/link", response_model=LinkResult)
def link(activity_id: int, payload: LinkPayload) -> LinkResult:
    user_id = _require_v0_user()
    event = link_activity_to_session(v0_db_path(), user_id=user_id, activity_id=activity_id, session_id=payload.session_id)
    if event.status != "applied":
        raise HTTPException(status_code=400, detail=event.reason)
    return LinkResult(activity_id=activity_id, session_id=payload.session_id, session_status=_session_status(payload.session_id))


@router.post("/api/v0/activities/{activity_id}/unlink", response_model=LinkResult)
def unlink(activity_id: int) -> LinkResult:
    user_id = _require_v0_user()
    event = unlink_activity(v0_db_path(), user_id=user_id, activity_id=activity_id)
    if event.status != "applied":
        raise HTTPException(status_code=400, detail=event.reason)
    linked = event.before.get("session") if isinstance(event.before, dict) else None
    session_id = linked.get("id") if isinstance(linked, dict) else None
    return LinkResult(activity_id=activity_id, session_id=session_id, session_status=_session_status(session_id) if session_id else None)
