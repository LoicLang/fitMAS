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


def test_user_scoped_commands_use_executor_user_id(tmp_path):
    db_path = _db(tmp_path)
    expires_at = datetime(2026, 5, 23, 14, 0, tzinfo=PARIS)

    CommandExecutor(db_path).execute(
        (
            CreatePendingConfirmationCommand("plan_patch", "move", "{}", expires_at),
            UpsertMemoryFactCommand("constraint", "Voyage", 0.9, expires_at),
            UpdateConversationStateCommand({"type": "move_session"}, None, None),
        ),
        turn_id="turn-user-42",
        user_id=42,
    )

    with connect(db_path) as connection:
        pending = connection.execute("select user_id from v0_pending_confirmations").fetchone()
        fact = connection.execute("select user_id from v0_facts").fetchone()
        state = connection.execute("select user_id from v0_conversation_state where user_id = 42").fetchone()
        event = connection.execute("select target_type, target_id from v0_command_events where command_type = 'UpdateConversationStateCommand'").fetchone()
    assert pending["user_id"] == 42
    assert fact["user_id"] == 42
    assert state["user_id"] == 42
    assert (event["target_type"], event["target_id"]) == ("state", "42")


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


def _open_week_pending(db_path, pending_id=1, ptype="week_proposal"):
    payload = {
        "type": "week_proposal",
        "week_proposal": {
            "week_start": "2026-06-15",
            "source": "llm",
            "week_load": 350.0,
            "key_type": "threshold",
            "sessions": [
                {"date": "2026-06-16", "type": "threshold", "duration_min": 50, "intensity": "hard", "detail": "3x8"},
            ],
        },
    }
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_pending_confirmations (id, user_id, type, summary, payload_json, status, expires_at) "
            "values (?, ?, ?, ?, ?, 'open', ?)",
            (pending_id, 1, ptype, "semaine du 15 juin", json.dumps(payload), "2026-06-30T00:00:00+00:00"),
        )
        connection.commit()


def test_resolve_pending_accept_commits_week(tmp_path):
    from fitmas.runtime_v0.policy import ResolvePendingConfirmationCommand

    db_path = _db(tmp_path)
    _open_week_pending(db_path, pending_id=1)

    events = CommandExecutor(db_path).execute(
        (ResolvePendingConfirmationCommand(pending_id=1, decision="accept", note=""),),
        turn_id="turn-accept",
    )

    with connect(db_path) as connection:
        week = connection.execute("select * from v0_planned_weeks").fetchone()
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert events[0].status == "applied"
    assert week["week_start"] == "2026-06-15"
    assert week["key_type"] == "threshold"
    assert json.loads(week["sessions_json"])[0]["type"] == "threshold"
    assert pending["status"] == "accepted"


def test_resolve_pending_reject_drops_without_store_write(tmp_path):
    from fitmas.runtime_v0.policy import ResolvePendingConfirmationCommand

    db_path = _db(tmp_path)
    _open_week_pending(db_path, pending_id=1)

    events = CommandExecutor(db_path).execute(
        (ResolvePendingConfirmationCommand(pending_id=1, decision="reject", note="pas cette semaine"),),
        turn_id="turn-reject",
    )

    with connect(db_path) as connection:
        week_count = connection.execute("select count(*) from v0_planned_weeks").fetchone()[0]
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert events[0].status == "applied"
    assert week_count == 0
    assert pending["status"] == "rejected"


def test_resolve_pending_accept_unsupported_type_fails_loud(tmp_path):
    from fitmas.runtime_v0.policy import ResolvePendingConfirmationCommand

    db_path = _db(tmp_path)
    _open_week_pending(db_path, pending_id=1, ptype="plan_patch")

    events = CommandExecutor(db_path).execute(
        (ResolvePendingConfirmationCommand(pending_id=1, decision="accept", note=""),),
        turn_id="turn-bad",
    )

    with connect(db_path) as connection:
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert events[0].status == "blocked"
    assert "pending_commit_not_supported_for_type" in events[0].reason
    assert pending["status"] == "open"  # rolled back, not lost


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


def test_new_week_pending_supersedes_prior_open_week_pending(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    executor = CommandExecutor(db_path)
    expires = datetime(2026, 12, 31, tzinfo=PARIS)

    def _week_pending(summary):
        return CreatePendingConfirmationCommand(
            type="week_proposal", summary=summary, payload_json="{}", expires_at=expires
        )

    executor.execute((_week_pending("semaine A"),), turn_id="t1")
    executor.execute((_week_pending("semaine B"),), turn_id="t2")

    with connect(db_path) as connection:
        rows = connection.execute(
            "select summary, status from v0_pending_confirmations order by id"
        ).fetchall()
    status = {r["summary"]: r["status"] for r in rows}
    assert status == {"semaine A": "superseded", "semaine B": "open"}


def test_week_pending_does_not_supersede_other_pending_types(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    executor = CommandExecutor(db_path)
    expires = datetime(2026, 12, 31, tzinfo=PARIS)
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_pending_confirmations (user_id, type, summary, payload_json, expires_at) "
            "values (?, ?, ?, ?, ?)",
            (1, "plan_patch", "swap en attente", "{}", expires.isoformat()),
        )
        connection.commit()
    executor.execute(
        (CreatePendingConfirmationCommand(
            type="week_proposal", summary="semaine", payload_json="{}", expires_at=expires),),
        turn_id="t1",
    )
    with connect(db_path) as connection:
        rows = connection.execute(
            "select type, status from v0_pending_confirmations order by id"
        ).fetchall()
    status = {r["type"]: r["status"] for r in rows}
    assert status["plan_patch"] == "open"      # un autre type n'est pas touché
    assert status["week_proposal"] == "open"
