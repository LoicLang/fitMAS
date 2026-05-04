"""Operations plane — separated from the coaching tool plane.

Endpoints for debugging, manual triggers, and administrative actions.
All endpoints are prefixed with /ops/ and require debug mode.
These serve the operator/developer, not the LLM or the user.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.api_support import ensure_debug_enabled
from fitmas.coach_messages import persist_draft
from fitmas.db import get_db
from fitmas.telegram_channel import resolve_chat_id, send_text_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"])


# ---------------------------------------------------------------------------
# Signal inspection
# ---------------------------------------------------------------------------

@router.get("/signals")
def get_signals(db: Session = Depends(get_db)) -> dict:
    """Inspect currently active signals for the user."""
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        return {"signals": []}
    from fitmas.signals import collect_signals
    return {"signals": collect_signals(db, user)}


# ---------------------------------------------------------------------------
# Heartbeat triggers
# ---------------------------------------------------------------------------

@router.post("/heartbeat/{kind}")
def trigger_heartbeat(
    kind: str,
    send: bool = True,
    dump: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """Manually trigger a heartbeat generation and optional delivery."""
    ensure_debug_enabled()

    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    import fitmas.heartbeat as heartbeat

    handlers = {
        "morning": heartbeat.morning_briefing,
        "pre_session": heartbeat.pre_session_reminder,
        "signal_check": heartbeat.signal_check,
        "weekly_review": heartbeat.weekly_review,
    }
    handler = handlers.get(kind)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Unsupported heartbeat kind: {kind}")

    trace = None
    if dump:
        with heartbeat.capture_debug_trace(kind) as captured:
            draft = handler()
            trace = captured
    else:
        draft = handler()
    if not draft:
        payload = {"kind": kind, "triggered": False, "sent": False, "reason": "no_op"}
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
    if dump and trace is not None:
        if not trace.decision:
            trace.decision = {"action": "send", "reason": "draft_generated"}
        if not trace.final.get("message"):
            trace.final = {"message": draft.text}
        payload["debug"] = trace.to_dict()
    return payload


# ---------------------------------------------------------------------------
# Memory inspection
# ---------------------------------------------------------------------------

@router.get("/memory")
def get_memory_state(db: Session = Depends(get_db)) -> dict:
    """Inspect current memory state: facts, working memory, patterns."""
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        return {"facts": [], "working_memory": [], "patterns": []}

    items = repo.get_active_memory_items(
        db, user.id,
        profile_limit=50,
        working_limit=50,
        include_patterns=True,
        pattern_limit=20,
        total_limit=100,
    )
    return {
        "total_items": len(items),
        "items": [
            {
                "category": getattr(item, "category", None),
                "key": getattr(item, "key", None),
                "value": getattr(item, "value", None),
                "urgency": getattr(item, "urgency", None),
                "ttl": getattr(item, "ttl", None),
                "source": getattr(item, "source", "profile"),
            }
            for item in items
        ],
    }


# ---------------------------------------------------------------------------
# Mutation log inspection
# ---------------------------------------------------------------------------

@router.get("/mutations/recent")
def get_recent_mutations(limit: int = 10, db: Session = Depends(get_db)) -> dict:
    """Inspect recent adaptation events / mutation log."""
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        return {"events": []}

    events = repo.get_recent_adaptation_events(db, user.id, limit=limit)
    return {
        "total": len(events),
        "events": [
            {
                "id": event.id,
                "created_at": str(event.created_at) if hasattr(event, "created_at") else None,
                "data": event.event_data if hasattr(event, "event_data") else str(event),
            }
            for event in events
        ],
    }


# ---------------------------------------------------------------------------
# Tool usage stats
# ---------------------------------------------------------------------------

@router.get("/tool-stats")
def get_tool_stats(db: Session = Depends(get_db)) -> dict:
    """Return tool usage statistics from recent conversation turns."""
    ensure_debug_enabled()
    user = repo.get_user_optional(db)
    if user is None:
        return {"turns": 0, "tool_usage": {}}

    turns = repo.get_recent_conversation_turns(db, user.id, limit=50)
    tool_counts: dict[str, int] = {}
    for turn in turns:
        ctx = getattr(turn, "context", None) or {}
        if isinstance(ctx, dict):
            for key in ctx:
                if key.startswith("tool_"):
                    tool_counts[key] = tool_counts.get(key, 0) + 1

    return {"turns": len(turns), "tool_usage": tool_counts}


# ---------------------------------------------------------------------------
# Reset (destructive — kept from api_debug.py)
# ---------------------------------------------------------------------------

@router.post("/reset")
def reset(db: Session = Depends(get_db)) -> dict[str, str]:
    """Reset all user data. Destructive operation."""
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
