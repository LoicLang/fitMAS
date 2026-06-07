from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Literal

from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.state import ConversationState

@dataclass(frozen=True)
class SessionView:
    id: int
    date: date
    sport: str
    title: str
    duration_min: int
    intensity_label: str
    priority: Literal["key", "secondary", "optional"]
    status: Literal["planned", "done", "skipped", "partial"]

@dataclass(frozen=True)
class ActivityView:
    id: int
    date: date
    sport: str
    duration_min: int
    distance_km: float | None
    notes: str | None
    source: Literal["strava", "manual"]

@dataclass(frozen=True)
class FactView:
    id: int
    kind: Literal["preference", "health", "availability", "constraint", "goal"]
    text: str
    confidence: float
    created_at: datetime
    expires_at: datetime | None

@dataclass(frozen=True)
class PendingView:
    id: int
    type: str
    summary: str
    expires_at: datetime

@dataclass(frozen=True)
class CommandEventView:
    id: int
    type: str
    target_session_id: int | None
    status: Literal["applied", "blocked"]
    summary: str
    created_at: datetime

@dataclass(frozen=True)
class SnapshotHeader:
    today: date
    timezone: str
    objective: str | None
    next_3_sessions: tuple[SessionView, ...]
    active_facts_summary: tuple[str, ...]
    pending: PendingView | None
    last_unresolved_intent: dict[str, Any] | None
    last_execution_event: CommandEventView | None
    recent_training: tuple[SessionView, ...] = ()

    def to_prompt_text(self) -> str:
        lines = [
            f"today: {self.today.isoformat()}",
            f"timezone: {self.timezone}",
            f"objective: {self.objective or 'none'}",
        ]
        if self.next_3_sessions:
            lines.append("next_sessions:")
            for session in self.next_3_sessions:
                lines.append(
                    "- "
                    f"{session.id} {session.date.isoformat()} {session.sport} "
                    f"{session.title} {session.duration_min}min "
                    f"{session.intensity_label} {session.priority} {session.status}"
                )
        if self.recent_training:
            lines.append("recent_training (last week, for week-planning seed):")
            for session in self.recent_training:
                lines.append(
                    "- "
                    f"{session.date.isoformat()} {session.sport} {session.title} "
                    f"{session.duration_min}min {session.intensity_label} "
                    f"{session.priority} {session.status}"
                )
        if self.active_facts_summary:
            lines.append("active_facts:")
            lines.extend(f"- {fact}" for fact in self.active_facts_summary)
        if self.pending is not None:
            lines.append(f"pending: {self.pending.id} {self.pending.summary}")
        if self.last_unresolved_intent is not None:
            lines.append(f"last_unresolved_intent: {json.dumps(self.last_unresolved_intent, sort_keys=True)}")
        if self.last_execution_event is not None:
            lines.append(
                "last_execution_event: "
                f"{self.last_execution_event.id} {self.last_execution_event.type} "
                f"{self.last_execution_event.summary}"
            )
        text = "\n".join(lines)
        assert len(text.split()) <= 500
        return text

@dataclass(frozen=True)
class WorldSnapshot:
    user_id: int
    today: date
    now: datetime
    timezone: str
    objective: str | None
    current_plan: tuple[SessionView, ...]
    recent_plan: tuple[SessionView, ...]
    recent_activities: tuple[ActivityView, ...]
    active_facts: tuple[FactView, ...]
    active_pending: PendingView | None
    recent_execution_events: tuple[CommandEventView, ...]
    recent_plan_events: tuple[CommandEventView, ...]
    conversation_state: ConversationState

    def header(self) -> SnapshotHeader:
        next_sessions = self.current_plan[:3]
        facts = tuple(fact.text for fact in self.active_facts[:5])
        last_execution_event = self.recent_execution_events[0] if self.recent_execution_events else None
        assert len(next_sessions) <= 3
        assert len(facts) <= 5
        return SnapshotHeader(
            today=self.today,
            timezone=self.timezone,
            objective=self.objective,
            next_3_sessions=next_sessions,
            active_facts_summary=facts,
            pending=self.active_pending,
            last_unresolved_intent=self.conversation_state.last_unresolved_intent,
            last_execution_event=last_execution_event,
            recent_training=self.recent_plan[:6],
        )

class SnapshotBuilder:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def build(self, user_id: int, now: datetime) -> WorldSnapshot:
        now = _ensure_timezone(now)
        today = now.date()
        with connect(self.db_path) as connection:
            recent_plan = _load_sessions(connection, user_id, today - timedelta(days=7), today - timedelta(days=1))
            current_plan = _load_sessions(connection, user_id, today, today + timedelta(days=14))
            recent_activities = _load_activities(connection, user_id, today - timedelta(days=21), today)
            active_facts = _load_active_facts(connection, user_id, now)
            active_pending = _load_pending(connection, user_id, now)
            recent_execution_events = _load_command_events(
                connection,
                ("SetSessionStatusCommand", "CorrectSessionStatusCommand"),
            )
            recent_plan_events = _load_command_events(connection, ("ApplyPlanPatchCommand",))
            conversation_state = _load_conversation_state(connection, user_id, now)

        assert len(active_facts) <= 10
        assert len(recent_execution_events) <= 5
        assert len(recent_plan_events) <= 5
        return WorldSnapshot(
            user_id=user_id,
            today=today,
            now=now,
            timezone=_timezone_name(now),
            objective=None,
            current_plan=current_plan,
            recent_plan=recent_plan,
            recent_activities=recent_activities,
            active_facts=active_facts,
            active_pending=active_pending,
            recent_execution_events=recent_execution_events,
            recent_plan_events=recent_plan_events,
            conversation_state=conversation_state,
        )

def _load_sessions(connection, user_id: int, start: date, end: date) -> tuple[SessionView, ...]:
    rows = connection.execute(
        "select * from v0_scheduled_sessions where user_id = ? and date between ? and ? order by date asc, id asc",
        (user_id, _date_text(start), _date_text(end)),
    ).fetchall()
    return tuple(_session_from_row(row) for row in rows)

def _load_activities(connection, user_id: int, start: date, end: date) -> tuple[ActivityView, ...]:
    rows = connection.execute(
        "select * from v0_activities where user_id = ? and date between ? and ? order by date asc, id asc",
        (user_id, _date_text(start), _date_text(end)),
    ).fetchall()
    return tuple(_activity_from_row(row) for row in rows)

def _load_active_facts(connection, user_id: int, now: datetime) -> tuple[FactView, ...]:
    rows = connection.execute(
        """
        select * from v0_facts
        where user_id = ? and (expires_at is null or expires_at > ?)
        and resolved_at is null
        order by created_at desc, id desc limit 10
        """,
        (user_id, now.isoformat()),
    ).fetchall()
    return tuple(_fact_from_row(row) for row in rows)

def _load_pending(connection, user_id: int, now: datetime) -> PendingView | None:
    row = connection.execute(
        "select * from v0_pending_confirmations where user_id = ? and status = 'open' and expires_at > ? order by expires_at asc, id asc limit 1",
        (user_id, now.isoformat()),
    ).fetchone()
    if row is None:
        return None
    return PendingView(
        id=row["id"],
        type=row["type"],
        summary=row["summary"],
        expires_at=_parse_datetime(row["expires_at"]),
    )

def _load_command_events(connection, command_types: tuple[str, ...]) -> tuple[CommandEventView, ...]:
    placeholders = ",".join("?" for _ in command_types)
    rows = connection.execute(
        f"""
        select * from v0_command_events
        where command_type in ({placeholders})
        order by created_at desc, id desc
        limit 5
        """,
        command_types,
    ).fetchall()
    return tuple(_command_event_from_row(row) for row in rows)

def _load_conversation_state(connection, user_id: int, now: datetime) -> ConversationState:
    row = connection.execute(
        "select * from v0_conversation_state where user_id = ?", (user_id,),
    ).fetchone()
    if row is None:
        return ConversationState(None, None, None, None, None)
    intent = json.loads(row["last_unresolved_intent_json"]) if row["last_unresolved_intent_json"] else None
    state = ConversationState(
        last_unresolved_intent=intent,
        last_execution_event_id=row["last_execution_event_id"],
        last_pending_id=row["last_pending_id"],
        last_user_turn_id=row["last_user_turn_id"],
        expires_at=_parse_optional_datetime(row["expires_at"]),
    )
    return state.active_at(now)

def _session_from_row(row) -> SessionView:
    return SessionView(
        id=row["id"], date=date.fromisoformat(row["date"]), sport=row["sport"], title=row["title"],
        duration_min=row["duration_min"], intensity_label=row["intensity_label"], priority=row["priority"], status=row["status"],
    )

def _activity_from_row(row) -> ActivityView:
    return ActivityView(
        id=row["id"], date=date.fromisoformat(row["date"]), sport=row["sport"], duration_min=row["duration_min"],
        distance_km=row["distance_km"], notes=row["notes"], source=row["source"],
    )

def _fact_from_row(row) -> FactView:
    return FactView(
        id=row["id"], kind=row["kind"], text=row["text"], confidence=row["confidence"],
        created_at=_parse_datetime(row["created_at"]), expires_at=_parse_optional_datetime(row["expires_at"]),
    )

def _command_event_from_row(row) -> CommandEventView:
    return CommandEventView(
        id=row["id"], type=row["command_type"], target_session_id=_target_session_id(row["target_type"], row["target_id"]),
        status=row["status"], summary=row["reason"], created_at=_parse_datetime(row["created_at"]),
    )

def _target_session_id(target_type: str, target_id: str) -> int | None:
    if target_type != "session":
        return None
    try:
        return int(target_id)
    except ValueError:
        return None

def _parse_optional_datetime(value: str | None) -> datetime | None:
    return _parse_datetime(value) if value else None

def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)
    parsed = datetime.fromisoformat(normalized)
    return _ensure_timezone(parsed)

def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

def _timezone_name(value: datetime) -> str:
    return getattr(value.tzinfo, "key", value.tzname() or "UTC")

def _date_text(value: date) -> str:
    return value.isoformat()
