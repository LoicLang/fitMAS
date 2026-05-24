from __future__ import annotations

from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.executor import CommandExecutor
from fitmas.runtime_v0.policy import (
    ApplyPlanPatchCommand,
    CorrectSessionStatusCommand,
    CreatePendingConfirmationCommand,
    SetSessionStatusCommand,
    UpdateConversationStateCommand,
    UpsertMemoryFactCommand,
)
from fitmas.runtime_v0.proposals import PlanPatchOperation


PARIS = ZoneInfo("Europe/Paris")


def _db(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            """
            insert into v0_scheduled_sessions (
                id, user_id, date, sport, title, duration_min,
                intensity_label, priority, status
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (60, 1, "2026-05-22", "run", "Footing", 45, "easy", "secondary", "planned"),
        )
        connection.execute(
            """
            insert into v0_scheduled_sessions (
                id, user_id, date, sport, title, duration_min,
                intensity_label, priority, status
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (61, 1, "2026-05-23", "bike", "Endurance", 60, "easy", "secondary", "planned"),
        )
        connection.commit()
    return db_path


def _insert_previous_event(db_path):
    with connect(db_path) as connection:
        connection.execute("insert into v0_turns (id) values (?)", ("previous-turn",))
        connection.execute(
            """
            insert into v0_command_events (
                id, turn_id, command_type, target_type, target_id,
                status, before_json, after_json, reason, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                17,
                "previous-turn",
                "SetSessionStatusCommand",
                "session",
                "60",
                "applied",
                "{}",
                "{}",
                "previous",
                datetime(2026, 5, 22, 13, 0, tzinfo=PARIS).isoformat(),
            ),
        )
        connection.commit()


def test_set_session_status_updates_session_and_appends_event(tmp_path):
    db_path = _db(tmp_path)

    events = CommandExecutor(db_path).execute(
        (
            SetSessionStatusCommand(
                session_id=60,
                status="skipped",
                duration_min=None,
                intensity_note=None,
                evidence="user skipped",
            ),
        ),
        turn_id="turn-1",
    )

    with connect(db_path) as connection:
        session = connection.execute("select status from v0_scheduled_sessions where id = 60").fetchone()
        rows = connection.execute("select * from v0_command_events").fetchall()
    assert session["status"] == "skipped"
    assert len(rows) == 1
    assert events[0].status == "applied"
    assert events[0].before["status"] == "planned"
    assert events[0].after["status"] == "skipped"


def test_correct_session_status_requires_previous_event(tmp_path):
    db_path = _db(tmp_path)
    _insert_previous_event(db_path)

    events = CommandExecutor(db_path).execute(
        (
            CorrectSessionStatusCommand(
                previous_event_id=17,
                session_id=60,
                status="done",
                duration_min=25,
                intensity_note="easy",
                evidence="user corrected",
            ),
        ),
        turn_id="turn-2",
    )

    with connect(db_path) as connection:
        session = connection.execute(
            "select status, duration_min from v0_scheduled_sessions where id = 60"
        ).fetchone()
    assert session["status"] == "done"
    assert session["duration_min"] == 25
    assert events[0].status == "applied"


def test_apply_plan_patch_move_updates_date(tmp_path):
    db_path = _db(tmp_path)

    events = CommandExecutor(db_path).execute(
        (
            ApplyPlanPatchCommand(
                operations=(
                    PlanPatchOperation(kind="move", source_session_id=60, target_date=datetime(2026, 5, 24).date()),
                ),
                rationale="move recovery",
            ),
        ),
        turn_id="turn-3",
    )

    with connect(db_path) as connection:
        session = connection.execute("select date from v0_scheduled_sessions where id = 60").fetchone()
    assert session["date"] == "2026-05-24"
    assert events[0].target_id == "60"


def test_create_pending_memory_and_state_commands(tmp_path):
    db_path = _db(tmp_path)
    expires_at = datetime(2026, 5, 23, 14, 0, tzinfo=PARIS)

    events = CommandExecutor(db_path).execute(
        (
            CreatePendingConfirmationCommand(
                type="plan_patch",
                summary="move key session",
                payload_json='{"type":"plan_patch"}',
                expires_at=expires_at,
            ),
            UpsertMemoryFactCommand(
                kind="constraint",
                text="Piscine fermée",
                confidence=0.8,
                expires_at=expires_at + timedelta(days=14),
            ),
            UpdateConversationStateCommand(
                last_unresolved_intent={"type": "move_session"},
                last_execution_event_id=17,
                last_pending_id=1,
            ),
        ),
        turn_id="turn-4",
    )

    with connect(db_path) as connection:
        pending = connection.execute("select summary from v0_pending_confirmations").fetchone()
        fact = connection.execute("select text from v0_facts").fetchone()
        state = connection.execute("select * from v0_conversation_state where user_id = 1").fetchone()
    assert pending["summary"] == "move key session"
    assert fact["text"] == "Piscine fermée"
    assert json.loads(state["last_unresolved_intent_json"]) == {"type": "move_session"}
    assert len(events) == 3
    assert all(event.status == "applied" for event in events)


def test_execute_is_transactional_per_command_and_stops_after_block(tmp_path):
    db_path = _db(tmp_path)

    events = CommandExecutor(db_path).execute(
        (
            SetSessionStatusCommand(
                session_id=60,
                status="skipped",
                duration_min=None,
                intensity_note=None,
                evidence="first ok",
            ),
            SetSessionStatusCommand(
                session_id=999,
                status="skipped",
                duration_min=None,
                intensity_note=None,
                evidence="second fails",
            ),
            UpsertMemoryFactCommand(kind="preference", text="should not run", confidence=0.9, expires_at=None),
        ),
        turn_id="turn-5",
    )

    with connect(db_path) as connection:
        session = connection.execute("select status from v0_scheduled_sessions where id = 60").fetchone()
        fact_count = connection.execute("select count(*) from v0_facts").fetchone()[0]
        event_rows = connection.execute("select status, reason from v0_command_events order by id").fetchall()
    assert session["status"] == "skipped"
    assert fact_count == 0
    assert [event.status for event in events] == ["applied", "blocked"]
    assert [row["status"] for row in event_rows] == ["applied", "blocked"]
    assert "session_not_found" in event_rows[-1]["reason"]


def test_execute_is_idempotent_by_turn_command_and_target(tmp_path):
    db_path = _db(tmp_path)
    command = SetSessionStatusCommand(
        session_id=60,
        status="skipped",
        duration_min=None,
        intensity_note=None,
        evidence="same turn",
    )
    executor = CommandExecutor(db_path)

    first = executor.execute((command,), turn_id="turn-6")
    second = executor.execute((command,), turn_id="turn-6")

    with connect(db_path) as connection:
        event_count = connection.execute("select count(*) from v0_command_events").fetchone()[0]
    assert event_count == 1
    assert first[0].id == second[0].id
