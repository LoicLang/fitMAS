from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.snapshot import (
    FactView,
    SessionView,
    WorldSnapshot,
)

@dataclass
class ToolContext:
    db_path: Path
    snapshot: WorldSnapshot
    scratchpad: dict[str, Any] = field(default_factory=dict)

def get_current_plan(ctx: ToolContext, days: int = 7) -> dict[str, Any]:
    name = "get_current_plan"
    clipped_days = max(1, min(days, 14))
    end = ctx.snapshot.today + timedelta(days=clipped_days)
    sessions = [
        _session_to_dict(session)
        for session in ctx.snapshot.current_plan
        if ctx.snapshot.today <= session.date <= end
    ]
    _record(ctx, name, True)
    return {
        "today": ctx.snapshot.today.isoformat(),
        "timezone": ctx.snapshot.timezone,
        "sessions": sessions,
    }

def get_plan_day(ctx: ToolContext, date: str) -> dict[str, Any]:
    name = "get_plan_day"
    try:
        target = _parse_date(date)
    except ValueError:
        _record(ctx, name, False)
        raise
    start = ctx.snapshot.today - timedelta(days=7)
    end = ctx.snapshot.today + timedelta(days=14)
    if target < start or target > end:
        _record(ctx, name, False)
        raise ValueError("outside_allowed_window")
    sessions = [
        _session_to_dict(session)
        for session in (*ctx.snapshot.recent_plan, *ctx.snapshot.current_plan)
        if session.date == target
    ]
    _record(ctx, name, True)
    return {"date": target.isoformat(), "sessions": sessions}

def get_session(ctx: ToolContext, session_id: int) -> dict[str, Any]:
    name = "get_session"
    for session in (*ctx.snapshot.recent_plan, *ctx.snapshot.current_plan):
        if session.id == session_id:
            _record(ctx, name, True)
            return _session_to_dict(session)
    _record(ctx, name, False)
    raise LookupError("session_not_found")

def get_recent_execution_events(ctx: ToolContext, limit: int = 5) -> dict[str, Any]:
    name = "get_recent_execution_events"
    clipped_limit = max(1, min(limit, 10))
    with connect(ctx.db_path) as connection:
        rows = connection.execute(
            """
            select * from v0_command_events
            where command_type in (?, ?)
            order by created_at desc, id desc
            limit ?
            """,
            ("SetSessionStatusCommand", "CorrectSessionStatusCommand", clipped_limit),
        ).fetchall()
    events = [
        {
            "id": row["id"],
            "type": row["command_type"],
            "target_session_id": _target_session_id(row["target_type"], row["target_id"]),
            "status": row["status"],
            "summary": row["reason"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    _record(ctx, name, True)
    return {"events": events}

def get_active_facts(ctx: ToolContext) -> dict[str, Any]:
    name = "get_active_facts"
    _record(ctx, name, True)
    return {"facts": [_fact_to_dict(fact) for fact in ctx.snapshot.active_facts]}

def _record(ctx: ToolContext, name: str, ok: bool) -> None:
    calls = ctx.scratchpad.setdefault("calls", [])
    calls.append({"name": name, "ok": ok})

def _session_to_dict(session: SessionView) -> dict[str, Any]:
    return {
        "id": session.id, "date": session.date.isoformat(), "sport": session.sport, "title": session.title,
        "duration_min": session.duration_min, "intensity_label": session.intensity_label,
        "priority": session.priority, "status": session.status,
    }

def _fact_to_dict(fact: FactView) -> dict[str, Any]:
    return {
        "id": fact.id, "kind": fact.kind, "text": fact.text, "confidence": fact.confidence,
        "created_at": fact.created_at.isoformat(), "expires_at": fact.expires_at.isoformat() if fact.expires_at else None,
    }

def _target_session_id(target_type: str, target_id: str) -> int | None:
    if target_type != "session":
        return None
    try:
        return int(target_id)
    except ValueError:
        return None

def _parse_date(value: str) -> date:
    return date.fromisoformat(value)
