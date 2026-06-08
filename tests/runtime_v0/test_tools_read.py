from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.snapshot import SnapshotBuilder
from fitmas.runtime_v0 import tools_read
from fitmas.runtime_v0.tools_read import (
    ToolContext,
    get_active_facts,
    get_current_plan,
    get_plan_day,
    get_planned_week,
    get_recent_execution_events,
    get_session,
)


PARIS = ZoneInfo("Europe/Paris")


def _date(now: datetime, offset: int) -> str:
    return (now.date() + timedelta(days=offset)).isoformat()


def _insert_session(connection, now: datetime, offset: int, session_id: int):
    connection.execute(
        """
        insert into v0_scheduled_sessions (
            id, user_id, date, sport, title, duration_min,
            intensity_label, priority, status
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, 1, _date(now, offset), "run", f"Session {offset}", 45, "easy", "secondary", "planned"),
    )


def _context(tmp_path, now: datetime) -> ToolContext:
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    return ToolContext(db_path=db_path, snapshot=SnapshotBuilder(db_path).build(1, now), scratchpad={})


def test_get_current_plan_clips_days_to_fourteen(tmp_path):
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    ctx = _context(tmp_path, now)
    with connect(ctx.db_path) as connection:
        _insert_session(connection, now, 0, 100)
        _insert_session(connection, now, 14, 114)
        _insert_session(connection, now, 15, 115)
        connection.commit()
    ctx = ToolContext(ctx.db_path, SnapshotBuilder(ctx.db_path).build(1, now), {})

    result = get_current_plan(ctx, days=99)

    assert [session["id"] for session in result["sessions"]] == [100, 114]
    assert ctx.scratchpad["calls"] == [{"name": "get_current_plan", "ok": True}]


def test_get_plan_day_rejects_dates_outside_window(tmp_path):
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    ctx = _context(tmp_path, now)

    with pytest.raises(ValueError, match="outside_allowed_window"):
        get_plan_day(ctx, _date(now, 15))

    assert ctx.scratchpad["calls"] == [{"name": "get_plan_day", "ok": False}]


def test_resolve_date_reference_returns_next_future_weekday(tmp_path):
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    ctx = _context(tmp_path, now)

    result = tools_read.resolve_date_reference(ctx, weekday="friday", direction="future")

    assert result == {
        "base_date": "2026-05-22",
        "weekday": "friday",
        "direction": "future",
        "date": "2026-05-29",
    }
    assert ctx.scratchpad["calls"] == [{"name": "resolve_date_reference", "ok": True}]


def test_resolve_date_reference_returns_typed_relative_day(tmp_path):
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    ctx = _context(tmp_path, now)

    today = tools_read.resolve_date_reference(ctx, relative_day="today")
    tomorrow = tools_read.resolve_date_reference(ctx, relative_day="tomorrow")

    assert today == {
        "base_date": "2026-05-22",
        "relative_day": "today",
        "date": "2026-05-22",
    }
    assert tomorrow == {
        "base_date": "2026-05-22",
        "relative_day": "tomorrow",
        "date": "2026-05-23",
    }
    assert ctx.scratchpad["calls"] == [
        {"name": "resolve_date_reference", "ok": True},
        {"name": "resolve_date_reference", "ok": True},
    ]


def test_get_session_returns_detail_or_errors(tmp_path):
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    ctx = _context(tmp_path, now)
    with connect(ctx.db_path) as connection:
        _insert_session(connection, now, 0, 100)
        connection.commit()
    ctx = ToolContext(ctx.db_path, SnapshotBuilder(ctx.db_path).build(1, now), {})

    assert get_session(ctx, 100)["title"] == "Session 0"
    with pytest.raises(LookupError, match="session_not_found"):
        get_session(ctx, 999)


def test_get_recent_execution_events_clips_limit_to_ten(tmp_path):
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    ctx = _context(tmp_path, now)
    with connect(ctx.db_path) as connection:
        for idx in range(12):
            turn_id = f"turn-{idx}"
            connection.execute("insert into v0_turns (id) values (?)", (turn_id,))
            connection.execute(
                """
                insert into v0_command_events (
                    turn_id, command_type, target_type, target_id,
                    status, before_json, after_json, reason, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    "SetSessionStatusCommand",
                    "session",
                    str(100 + idx),
                    "applied",
                    "{}",
                    "{}",
                    f"event {idx}",
                    (now - timedelta(minutes=idx)).isoformat(),
                ),
            )
        connection.commit()

    result = get_recent_execution_events(ctx, limit=99)

    assert len(result["events"]) == 10
    assert result["events"][0]["summary"] == "event 0"


def test_get_planned_week_returns_latest_committed_week(tmp_path):
    import json
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json) "
            "values (?,?,?,?,?,?)",
            (1, "2026-06-15", "llm", 375.0, "threshold",
             json.dumps([{"date": "2026-06-16", "type": "threshold", "duration_min": 50, "intensity": "hard", "detail": ""}])),
        )
        conn.commit()
    now = datetime(2026, 6, 8, 10, 0, tzinfo=PARIS)
    ctx = ToolContext(db_path=db_path, snapshot=SnapshotBuilder(db_path).build(1, now), scratchpad={})

    result = get_planned_week(ctx)

    assert result["planned_week"]["week_start"] == "2026-06-15"
    assert result["planned_week"]["key_type"] == "threshold"
    assert len(result["planned_week"]["sessions"]) == 1
    assert result["planned_week"]["sessions"][0]["type"] == "threshold"


def test_get_planned_week_none_when_empty(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    now = datetime(2026, 6, 8, 10, 0, tzinfo=PARIS)
    ctx = ToolContext(db_path=db_path, snapshot=SnapshotBuilder(db_path).build(1, now), scratchpad={})

    assert get_planned_week(ctx)["planned_week"] is None


def test_get_active_facts_returns_non_expired_facts(tmp_path):
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    ctx = _context(tmp_path, now)
    with connect(ctx.db_path) as connection:
        connection.execute(
            """
            insert into v0_facts (user_id, kind, text, confidence, created_at, expires_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (1, "preference", "Aime courir matin", 0.9, now.isoformat(), None),
        )
        connection.execute(
            """
            insert into v0_facts (user_id, kind, text, confidence, created_at, expires_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (1, "constraint", "Ancienne contrainte", 0.9, now.isoformat(), (now - timedelta(days=1)).isoformat()),
        )
        connection.commit()
    ctx = ToolContext(ctx.db_path, SnapshotBuilder(ctx.db_path).build(1, now), {})

    result = get_active_facts(ctx)

    assert [fact["text"] for fact in result["facts"]] == ["Aime courir matin"]
