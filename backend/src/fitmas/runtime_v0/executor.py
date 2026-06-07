from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Literal

from fitmas.runtime_v0.db import connect
from fitmas.runtime_v0.policy import (
    ApplyPlanPatchCommand,
    Command,
    CorrectSessionStatusCommand,
    CreatePendingConfirmationCommand,
    ResolveMemoryFactCommand,
    ResolvePendingConfirmationCommand,
    SetSessionStatusCommand,
    UpdateConversationStateCommand,
    UpsertMemoryFactCommand,
)
from fitmas.runtime_v0.proposals import PlanPatchOperation

@dataclass(frozen=True)
class CommandEvent:
    id: int
    turn_id: str
    command_type: str
    target_type: str
    target_id: str
    status: Literal["applied", "blocked"]
    before: dict[str, Any]
    after: dict[str, Any]
    reason: str
    created_at: datetime

class CommandExecutor:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def execute(self, commands: tuple[Command, ...], turn_id: str, user_id: int = 1) -> tuple[CommandEvent, ...]:
        events: list[CommandEvent] = []
        _ensure_turn(self.db_path, turn_id)
        for command in commands:
            existing = _load_existing_event(self.db_path, turn_id, command, user_id)
            if existing is not None:
                events.append(existing)
                continue
            try:
                event = self._execute_one(command, turn_id, user_id)
            except Exception as exc:
                event = _record_blocked_event(self.db_path, turn_id, command, str(exc), user_id)
                events.append(event)
                break
            events.append(event)
        return tuple(events)

    def _execute_one(self, command: Command, turn_id: str, user_id: int) -> CommandEvent:
        with connect(self.db_path) as connection:
            try:
                before, after, reason = _apply_command(command, connection, user_id)
                event_id = _insert_event(
                    connection=connection,
                    turn_id=turn_id,
                    command=command,
                    user_id=user_id,
                    status="applied",
                    before=before,
                    after=after,
                    reason=reason,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        loaded = _load_event_by_id(self.db_path, event_id)
        if loaded is None:
            raise RuntimeError("command_event_missing_after_insert")
        return loaded

def _apply_command(command: Command, connection, user_id: int) -> tuple[dict[str, Any], dict[str, Any], str]:
    if isinstance(command, SetSessionStatusCommand):
        return _apply_set_session_status(command, connection)
    if isinstance(command, CorrectSessionStatusCommand):
        return _apply_correct_session_status(command, connection)
    if isinstance(command, ApplyPlanPatchCommand):
        return _apply_plan_patch(command, connection)
    if isinstance(command, CreatePendingConfirmationCommand):
        return _apply_create_pending(command, connection, user_id)
    if isinstance(command, UpsertMemoryFactCommand):
        return _apply_upsert_memory_fact(command, connection, user_id)
    if isinstance(command, ResolveMemoryFactCommand):
        return _apply_resolve_memory_fact(command, connection, user_id)
    if isinstance(command, ResolvePendingConfirmationCommand):
        return _apply_resolve_pending(command, connection, user_id)
    if isinstance(command, UpdateConversationStateCommand):
        return _apply_update_conversation_state(command, connection, user_id)
    raise ValueError("unsupported_command")

def _apply_set_session_status(command: SetSessionStatusCommand, connection) -> tuple[dict[str, Any], dict[str, Any], str]:
    before = _session_or_raise(connection, command.session_id)
    duration_min = command.duration_min if command.duration_min is not None else before["duration_min"]
    connection.execute(
        "update v0_scheduled_sessions set status = ?, duration_min = ?, updated_at = ? where id = ?",
        (command.status, duration_min, _now_text(), command.session_id),
    )
    after = _session(connection, command.session_id)
    return before, after, command.evidence

def _apply_correct_session_status(command: CorrectSessionStatusCommand, connection) -> tuple[dict[str, Any], dict[str, Any], str]:
    previous = connection.execute(
        "select id from v0_command_events where id = ?",
        (command.previous_event_id,),
    ).fetchone()
    if previous is None:
        raise ValueError("previous_event_not_found")
    before = _session_or_raise(connection, command.session_id)
    duration_min = command.duration_min if command.duration_min is not None else before["duration_min"]
    connection.execute(
        "update v0_scheduled_sessions set status = ?, duration_min = ?, intensity_label = coalesce(?, intensity_label), updated_at = ? where id = ?",
        (command.status, duration_min, command.intensity_note, _now_text(), command.session_id),
    )
    after = _session(connection, command.session_id)
    return before, after, command.evidence

def _apply_plan_patch(command: ApplyPlanPatchCommand, connection) -> tuple[dict[str, Any], dict[str, Any], str]:
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for operation in command.operations:
        before[str(operation.source_session_id)] = _session_or_raise(connection, operation.source_session_id)
        _apply_operation(connection, operation)
        after[str(operation.source_session_id)] = _session_or_raise(connection, operation.source_session_id)
    return before, after, command.rationale

def _apply_operation(connection, operation: PlanPatchOperation) -> None:
    if operation.kind == "move":
        if operation.target_date is None:
            raise ValueError("target_date_required")
        connection.execute(
            "update v0_scheduled_sessions set date = ?, updated_at = ? where id = ?",
            (operation.target_date.isoformat(), _now_text(), operation.source_session_id),
        )
        return
    if operation.kind == "swap":
        if operation.target_session_id is None:
            raise ValueError("target_session_id_required")
        first = _session_or_raise(connection, operation.source_session_id)
        second = _session_or_raise(connection, operation.target_session_id)
        connection.execute(
            "update v0_scheduled_sessions set date = ?, updated_at = ? where id = ?",
            (second["date"], _now_text(), operation.source_session_id),
        )
        connection.execute(
            "update v0_scheduled_sessions set date = ?, updated_at = ? where id = ?",
            (first["date"], _now_text(), operation.target_session_id),
        )
        return
    if operation.kind == "lighten":
        connection.execute(
            "update v0_scheduled_sessions set intensity_label = coalesce(?, intensity_label), duration_min = coalesce(?, duration_min), updated_at = ? where id = ?",
            (
                operation.new_intensity_label,
                operation.new_duration_min,
                _now_text(),
                operation.source_session_id,
            ),
        )
        return
    if operation.kind == "replace":
        connection.execute(
            "update v0_scheduled_sessions set sport = coalesce(?, sport), intensity_label = coalesce(?, intensity_label), duration_min = coalesce(?, duration_min), updated_at = ? where id = ?",
            (
                operation.new_sport,
                operation.new_intensity_label,
                operation.new_duration_min,
                _now_text(),
                operation.source_session_id,
            ),
        )
        return
    if operation.kind == "remove_optional":
        connection.execute(
            "update v0_scheduled_sessions set status = ?, updated_at = ? where id = ?",
            ("skipped", _now_text(), operation.source_session_id),
        )
        return
    raise ValueError("unsupported_plan_operation")

def _apply_create_pending(command: CreatePendingConfirmationCommand, connection, user_id: int) -> tuple[dict[str, Any], dict[str, Any], str]:
    cursor = connection.execute(
        "insert into v0_pending_confirmations (user_id, type, summary, payload_json, expires_at) values (?, ?, ?, ?, ?)",
        (user_id, command.type, command.summary, command.payload_json, command.expires_at.isoformat()),
    )
    row = _pending(connection, cursor.lastrowid)
    return {}, row, command.summary

def _apply_upsert_memory_fact(command: UpsertMemoryFactCommand, connection, user_id: int) -> tuple[dict[str, Any], dict[str, Any], str]:
    cursor = connection.execute(
        "insert into v0_facts (user_id, kind, text, confidence, expires_at) values (?, ?, ?, ?, ?)",
        (user_id, command.kind, command.text, command.confidence, command.expires_at.isoformat() if command.expires_at else None),
    )
    row = _fact(connection, cursor.lastrowid)
    return {}, row, command.text

def _apply_resolve_memory_fact(command: ResolveMemoryFactCommand, connection, user_id: int) -> tuple[dict[str, Any], dict[str, Any], str]:
    before_row = connection.execute(
        "select * from v0_facts where id = ? and user_id = ?", (command.fact_id, user_id)
    ).fetchone()
    if before_row is None:
        raise ValueError("fact_not_found")
    before = dict(before_row)
    connection.execute(
        "update v0_facts set resolved_at = ? where id = ? and user_id = ?",
        (_now_text(), command.fact_id, user_id),
    )
    after = _fact(connection, command.fact_id)
    return before, after, command.reason

def _apply_resolve_pending(command: ResolvePendingConfirmationCommand, connection, user_id: int) -> tuple[dict[str, Any], dict[str, Any], str]:
    row = connection.execute(
        "select * from v0_pending_confirmations where id = ? and user_id = ? and status = 'open'",
        (command.pending_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError("pending_not_open")
    before = dict(row)
    if command.decision == "reject":
        connection.execute(
            "update v0_pending_confirmations set status = 'rejected' where id = ? and user_id = ?",
            (command.pending_id, user_id),
        )
        after = _pending(connection, command.pending_id)
        return before, after, command.note or "rejected"
    payload = json.loads(before["payload_json"])
    if before["type"] == "week_proposal":
        after = _apply_commit_week(payload, connection, user_id)
    else:
        raise ValueError(f"pending_commit_not_supported_for_type:{before['type']}")
    connection.execute(
        "update v0_pending_confirmations set status = 'accepted' where id = ? and user_id = ?",
        (command.pending_id, user_id),
    )
    # Intentional asymmetry: `before` is the pending row, `after` is the committed
    # week row — the audit event shows what was actually committed on accept.
    return before, after, command.note or "accepted"


def _apply_commit_week(payload: dict[str, Any], connection, user_id: int) -> dict[str, Any]:
    week = payload.get("week_proposal")
    if not week:
        raise ValueError("pending_week_payload_missing")
    cursor = connection.execute(
        "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json) "
        "values (?, ?, ?, ?, ?, ?)",
        (
            user_id,
            week["week_start"],
            week["source"],
            week["week_load"],
            week["key_type"],
            json.dumps(week["sessions"], ensure_ascii=False),
        ),
    )
    row = connection.execute("select * from v0_planned_weeks where id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def _apply_update_conversation_state(command: UpdateConversationStateCommand, connection, user_id: int) -> tuple[dict[str, Any], dict[str, Any], str]:
    before = _conversation_state(connection, user_id) or {}
    intent_json = (
        json.dumps(command.last_unresolved_intent, ensure_ascii=False, sort_keys=True)
        if command.last_unresolved_intent is not None
        else None
    )
    connection.execute(
        """
        insert into v0_conversation_state (user_id, last_unresolved_intent_json, last_execution_event_id, last_pending_id, updated_at)
        values (?, ?, ?, ?, ?)
        on conflict(user_id) do update set last_unresolved_intent_json = excluded.last_unresolved_intent_json,
        last_execution_event_id = excluded.last_execution_event_id, last_pending_id = excluded.last_pending_id, updated_at = excluded.updated_at
        """,
        (user_id, intent_json, command.last_execution_event_id, command.last_pending_id, _now_text()),
    )
    after = _conversation_state(connection, user_id) or {}
    return before, after, "conversation_state_updated"

def _insert_event(
    connection,
    turn_id: str,
    command: Command,
    user_id: int,
    status: Literal["applied", "blocked"],
    before: dict[str, Any],
    after: dict[str, Any],
    reason: str,
) -> int:
    target_type, target_id = _target(command, user_id)
    cursor = connection.execute(
        "insert into v0_command_events (turn_id, command_type, target_type, target_id, status, before_json, after_json, reason) values (?, ?, ?, ?, ?, ?, ?, ?)",
        (turn_id, type(command).__name__, target_type, target_id, status, _json(before), _json(after), reason),
    )
    return cursor.lastrowid

def _record_blocked_event(db_path: Path, turn_id: str, command: Command, reason: str, user_id: int) -> CommandEvent:
    with connect(db_path) as connection:
        event_id = _insert_event(
            connection=connection,
            turn_id=turn_id,
            command=command,
            user_id=user_id,
            status="blocked",
            before={},
            after={},
            reason=reason,
        )
        connection.commit()
    loaded = _load_event_by_id(db_path, event_id)
    if loaded is None:
        raise RuntimeError("blocked_command_event_missing_after_insert")
    return loaded

def _load_existing_event(db_path: Path, turn_id: str, command: Command, user_id: int) -> CommandEvent | None:
    target_type, target_id = _target(command, user_id)
    with connect(db_path) as connection:
        row = connection.execute(
            "select * from v0_command_events where turn_id = ? and command_type = ? and target_id = ?",
            (turn_id, type(command).__name__, target_id),
        ).fetchone()
    return _event_from_row(row) if row else None

def _load_event_by_id(db_path: Path, event_id: int) -> CommandEvent | None:
    with connect(db_path) as connection:
        row = connection.execute("select * from v0_command_events where id = ?", (event_id,)).fetchone()
    return _event_from_row(row) if row else None

def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)

def _event_from_row(row) -> CommandEvent:
    return CommandEvent(
        id=row["id"],
        turn_id=row["turn_id"],
        command_type=row["command_type"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        status=row["status"],
        before=json.loads(row["before_json"]),
        after=json.loads(row["after_json"]),
        reason=row["reason"],
        created_at=datetime.fromisoformat(row["created_at"].replace(" ", "T")),
    )

def _ensure_turn(db_path: Path, turn_id: str) -> None:
    with connect(db_path) as connection:
        connection.execute("insert or ignore into v0_turns (id) values (?)", (turn_id,))
        connection.commit()

def _target(command: Command, user_id: int) -> tuple[str, str]:
    if isinstance(command, SetSessionStatusCommand):
        return "session", str(command.session_id)
    if isinstance(command, CorrectSessionStatusCommand):
        return "session", str(command.session_id)
    if isinstance(command, ApplyPlanPatchCommand):
        first = command.operations[0] if command.operations else None
        return "session", str(first.source_session_id if first else "none")
    if isinstance(command, CreatePendingConfirmationCommand):
        return "pending", command.type
    if isinstance(command, UpsertMemoryFactCommand):
        return "fact", command.text
    if isinstance(command, ResolveMemoryFactCommand):
        return "fact", str(command.fact_id)
    if isinstance(command, ResolvePendingConfirmationCommand):
        return "pending", str(command.pending_id)
    if isinstance(command, UpdateConversationStateCommand):
        return "state", str(user_id)
    return "unknown", type(command).__name__

def _session(connection, session_id: int) -> dict[str, Any] | None:
    row = connection.execute("select * from v0_scheduled_sessions where id = ?", (session_id,)).fetchone()
    return dict(row) if row else None

def _session_or_raise(connection, session_id: int) -> dict[str, Any]:
    row = _session(connection, session_id)
    if row is None:
        raise ValueError("session_not_found")
    return row

def _pending(connection, pending_id: int) -> dict[str, Any]:
    row = connection.execute("select * from v0_pending_confirmations where id = ?", (pending_id,)).fetchone()
    return dict(row)

def _fact(connection, fact_id: int) -> dict[str, Any]:
    row = connection.execute("select * from v0_facts where id = ?", (fact_id,)).fetchone()
    return dict(row)

def _conversation_state(connection, user_id: int) -> dict[str, Any] | None:
    row = connection.execute("select * from v0_conversation_state where user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None

def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()
