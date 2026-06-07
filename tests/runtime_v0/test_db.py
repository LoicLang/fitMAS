from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import sqlite3

import pytest

from fitmas.runtime_v0.db import connect, db_path_from_env, init_db, reset_db
from fitmas.runtime_v0.event import InputEvent


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "select name from sqlite_master where type = 'table'"
    ).fetchall()
    return {row["name"] for row in rows}


def test_db_path_defaults_to_local_v0_database(monkeypatch):
    monkeypatch.delenv("FITMAS_V0_DB_PATH", raising=False)

    assert db_path_from_env().as_posix() == "fitmas_v0.db"


def test_db_path_can_be_overridden(monkeypatch, tmp_path):
    path = tmp_path / "custom-v0.db"
    monkeypatch.setenv("FITMAS_V0_DB_PATH", str(path))

    assert db_path_from_env() == path


def test_init_db_creates_minimal_offline_schema(tmp_path):
    path = tmp_path / "fitmas_v0.db"

    init_db(path)

    with connect(path) as connection:
        assert {
            "v0_turns",
            "v0_command_events",
            "v0_scheduled_sessions",
            "v0_facts",
            "v0_conversation_state",
        }.issubset(_table_names(connection))
        lock_columns = {
            row["name"]
            for row in connection.execute("pragma table_info(v0_idempotency_locks)").fetchall()
        }
        assert {"event_id", "turn_id", "status", "updated_at"} <= lock_columns


def test_reset_db_recreates_empty_schema(tmp_path):
    path = tmp_path / "fitmas_v0.db"
    init_db(path)
    with connect(path) as connection:
        connection.execute(
            """
            insert into v0_scheduled_sessions (
                user_id, date, sport, title, duration_min,
                intensity_label, priority, status
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "2026-05-22", "run", "Footing", 45, "easy", "secondary", "planned"),
        )
        connection.commit()

    reset_db(path)

    with connect(path) as connection:
        count = connection.execute("select count(*) from v0_scheduled_sessions").fetchone()[0]
        assert count == 0
        assert "v0_turns" in _table_names(connection)


def test_planned_weeks_table_exists_and_resets(tmp_path):
    from fitmas.runtime_v0.db import connect, init_db, reset_db

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json) "
            "values (?, ?, ?, ?, ?, ?)",
            (1, "2026-06-15", "llm", 350.0, "threshold", "[]"),
        )
        connection.commit()
        row = connection.execute("select * from v0_planned_weeks").fetchone()
    assert row["status"] == "committed"
    assert row["week_start"] == "2026-06-15"

    reset_db(db_path)
    with connect(db_path) as connection:
        count = connection.execute("select count(*) from v0_planned_weeks").fetchone()[0]
    assert count == 0


def test_input_event_is_frozen_and_matches_contract():
    event = InputEvent(
        id="evt-1",
        user_id=1,
        source="test",
        type="user_message",
        text="Redonne-moi le plan actuel.",
        payload={"channel": "test"},
        occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc),
    )

    assert event.id == "evt-1"
    assert event.user_id == 1
    assert event.source == "test"
    assert event.type == "user_message"
    assert event.payload == {"channel": "test"}
    with pytest.raises(FrozenInstanceError):
        event.user_id = 2
