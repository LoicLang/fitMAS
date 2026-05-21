from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.app.api.support import ensure_debug_enabled
from fitmas.coach_messages import persist_draft
from fitmas.db import get_db
from fitmas.app.telegram.channel import resolve_chat_id, send_text_message

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v0/signals")
def get_signals(db: Session = Depends(get_db)) -> dict:
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        return {"signals": []}
    from fitmas.signals import collect_signals

    return {"signals": collect_signals(db, user)}


@router.post("/api/v0/debug/heartbeat/{kind}")
def trigger_debug_heartbeat(
    kind: str,
    send: bool = True,
    dump: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    ensure_debug_enabled()

    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    import fitmas.skills.heartbeat.heartbeat as heartbeat

    handlers = {
        "morning": heartbeat.morning_briefing,
        "pre_session": heartbeat.pre_session_reminder,
        "signal_check": heartbeat.signal_check,
        "weekly_review": heartbeat.weekly_review,
    }
    handler = handlers.get(kind)
    if handler is None:
        raise HTTPException(status_code=400, detail="Unsupported heartbeat kind")

    trace = None
    runtime_result = None
    if dump:
        with heartbeat.capture_debug_trace(kind) as captured:
            draft = handler()
            trace = captured
    else:
        import fitmas.skills.heartbeat.runtime_adapter as adapter

        runtime_result = adapter.run_heartbeat_endpoint(
            kind,
            handler,
            user_id=user.id,
            delivery_channel="debug",
        )
        draft = runtime_result.draft if runtime_result is not None else handler()
    if not draft:
        payload = {
            "kind": kind,
            "triggered": False,
            "sent": False,
            "reason": "no_op",
        }
        if runtime_result is not None:
            payload["runtime"] = adapter.heartbeat_runtime_payload(runtime_result)
        if dump and trace is not None:
            if not trace.decision:
                trace.decision = {"action": "no_send", "reason": "no_op"}
            trace.final = {"message": None}
            payload["debug"] = trace.to_dict()
        return payload

    sent = False
    delivery_error = None
    if send:
        chat_id = resolve_chat_id(db, user=user)
        if not chat_id:
            delivery_error = "missing_telegram_chat_id"
        else:
            try:
                sent = send_text_message(chat_id=chat_id, text=draft.text, parse_mode=draft.parse_mode)
                if sent:
                    persist_draft(user.id, draft, db=db)
            except Exception as exc:
                logger.exception("Failed to send debug heartbeat to Telegram")
                delivery_error = str(exc)

    payload = {
        "kind": kind,
        "triggered": True,
        "sent": sent,
        "delivery_error": delivery_error,
        "message": draft.text,
    }
    if runtime_result is not None:
        payload["runtime"] = adapter.heartbeat_runtime_payload(runtime_result)
    if dump and trace is not None:
        if not trace.decision:
            trace.decision = {"action": "send", "reason": "draft_generated"}
        if not trace.final.get("message"):
            trace.final = {"message": draft.text}
        payload["debug"] = trace.to_dict()
    return payload


@router.post("/api/v0/reset")
def reset(db: Session = Depends(get_db)) -> dict[str, str]:
    ensure_debug_enabled()
    db.query(s.WatchItem).delete()
    db.query(s.ChangeNote).delete()
    db.query(s.DayPlan).delete()
    db.query(s.WeeklyPlan).delete()
    db.query(s.CoachMessage).delete()
    db.query(s.Activity).delete()
    db.query(s.UserFact).delete()
    db.query(s.UserSport).delete()
    db.query(s.UserPreference).delete()
    db.query(s.UserConstraint).delete()
    db.query(s.User).delete()
    db.commit()
    return {"status": "reset ok"}
