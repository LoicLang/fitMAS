from __future__ import annotations

from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.snapshot import SnapshotBuilder


PARIS = ZoneInfo("Europe/Paris")


def _iso_date(now: datetime, offset_days: int) -> str:
    return (now.date() + timedelta(days=offset_days)).isoformat()


def _insert_session(connection, now: datetime, offset: int, session_id: int | None = None):
    columns = ["user_id", "date", "sport", "title", "duration_min", "intensity_label", "priority", "status"]
    values = [1, _iso_date(now, offset), "run", f"Session {offset}", 45, "easy", "secondary", "planned"]
    if session_id is not None:
        columns.insert(0, "id")
        values.insert(0, session_id)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"insert into v0_scheduled_sessions ({','.join(columns)}) values ({placeholders})",
        values,
    )


def _insert_activity(connection, now: datetime, offset: int):
    connection.execute(
        """
        insert into v0_activities (
            user_id, date, sport, duration_min, distance_km, notes, source
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (1, _iso_date(now, offset), "run", 30, 6.0, f"Activity {offset}", "manual"),
    )


def _insert_turn(connection, turn_id: str):
    connection.execute("insert into v0_turns (id) values (?)", (turn_id,))


def test_snapshot_uses_bounded_date_windows(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        for offset in (-8, -7, -1, 0, 14, 15):
            _insert_session(connection, now, offset)
        for offset in (-22, -21, 0):
            _insert_activity(connection, now, offset)
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now)

    assert [session.date.isoformat() for session in snapshot.recent_plan] == [
        _iso_date(now, -7),
        _iso_date(now, -1),
    ]
    assert [session.date.isoformat() for session in snapshot.current_plan] == [
        _iso_date(now, 0),
        _iso_date(now, 14),
    ]
    assert [activity.date.isoformat() for activity in snapshot.recent_activities] == [
        _iso_date(now, -21),
        _iso_date(now, 0),
    ]


def test_snapshot_caps_prompt_and_recent_context(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        for offset in range(6):
            _insert_session(connection, now, offset, session_id=100 + offset)
        for idx in range(12):
            connection.execute(
                """
                insert into v0_facts (user_id, kind, text, confidence, created_at, expires_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "preference",
                    f"Fact {idx}",
                    0.8,
                    (now - timedelta(minutes=idx)).isoformat(),
                    None,
                ),
            )
        connection.execute(
            """
            insert into v0_facts (user_id, kind, text, confidence, created_at, expires_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (1, "constraint", "Expired", 0.9, now.isoformat(), (now - timedelta(days=1)).isoformat()),
        )
        for idx in range(7):
            _insert_turn(connection, f"turn-exec-{idx}")
            connection.execute(
                """
                insert into v0_command_events (
                    turn_id, command_type, target_type, target_id,
                    status, before_json, after_json, reason, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"turn-exec-{idx}",
                    "SetSessionStatusCommand",
                    "session",
                    str(100 + idx),
                    "applied",
                    "{}",
                    "{}",
                    f"execution {idx}",
                    (now - timedelta(minutes=idx)).isoformat(),
                ),
            )
        for idx in range(6):
            _insert_turn(connection, f"turn-plan-{idx}")
            connection.execute(
                """
                insert into v0_command_events (
                    turn_id, command_type, target_type, target_id,
                    status, before_json, after_json, reason, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"turn-plan-{idx}",
                    "ApplyPlanPatchCommand",
                    "session",
                    str(100 + idx),
                    "applied",
                    "{}",
                    "{}",
                    f"plan {idx}",
                    (now - timedelta(minutes=idx)).isoformat(),
                ),
            )
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now)
    header = snapshot.header()

    assert len(snapshot.active_facts) == 10
    assert all(fact.text != "Expired" for fact in snapshot.active_facts)
    assert len(snapshot.recent_execution_events) == 5
    assert len(snapshot.recent_plan_events) == 5
    assert len(header.next_3_sessions) == 3
    assert len(header.active_facts_summary) == 5
    assert len(header.to_prompt_text().split()) <= 500


def test_expired_conversation_state_is_omitted_from_header(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            """
            insert into v0_conversation_state (
                user_id, last_unresolved_intent_json, expires_at
            ) values (?, ?, ?)
            """,
            (
                1,
                json.dumps({"type": "move_session", "target_date": "2026-05-24"}),
                (now - timedelta(minutes=1)).isoformat(),
            ),
        )
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now)

    assert snapshot.conversation_state.last_unresolved_intent is None
    assert snapshot.header().last_unresolved_intent is None


def test_snapshot_loads_last_committed_week(tmp_path):
    from datetime import datetime, timezone
    from fitmas.runtime_v0.db import connect, init_db
    from fitmas.runtime_v0.meso.model import WeekActuals
    from fitmas.runtime_v0.snapshot import SnapshotBuilder

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json) "
            "values (?, ?, ?, ?, ?, ?)",
            (1, "2026-06-01", "llm", 300.0, "threshold", "[]"),
        )
        connection.execute(
            "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json) "
            "values (?, ?, ?, ?, ?, ?)",
            (1, "2026-06-08", "llm", 330.0, "intervals", "[]"),
        )
        # A later but non-committed week must be excluded by the status filter:
        # if the filter regressed, this latest-week_start row would be picked.
        connection.execute(
            "insert into v0_planned_weeks (user_id, week_start, source, week_load, key_type, sessions_json, status) "
            "values (?, ?, ?, ?, ?, ?, ?)",
            (1, "2026-06-15", "llm", 999.0, "easy_run", "[]", "superseded"),
        )
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(1, datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc))
    assert snapshot.last_planned_week == WeekActuals(total_load=330.0, key_type="intervals")


def _insert_input_event(connection, event_id: str, now, text: str, hours_ago: float):
    connection.execute(
        "insert into v0_input_events (id, user_id, source, type, text, payload_json, occurred_at)"
        " values (?, 1, 'test', 'user_message', ?, '{}', ?)",
        (event_id, text, (now - timedelta(hours=hours_ago)).isoformat()),
    )


def _insert_turn_reply(connection, turn_id: str, event_id: str, reply: str):
    connection.execute(
        "insert into v0_turns (id, event_id, reply) values (?, ?, ?)",
        (turn_id, event_id, reply),
    )


def test_transcript_keeps_last_four_exchanges_chronological(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        for index in range(6):
            _insert_input_event(connection, f"evt-{index}", now, f"message {index}", hours_ago=6 - index)
            _insert_turn_reply(connection, f"turn-{index}", f"evt-{index}", f"reponse {index}")
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now)

    entries = [(entry.role, entry.text) for entry in snapshot.recent_transcript]
    assert entries == [
        ("user", "message 2"), ("coach", "reponse 2"),
        ("user", "message 3"), ("coach", "reponse 3"),
        ("user", "message 4"), ("coach", "reponse 4"),
        ("user", "message 5"), ("coach", "reponse 5"),
    ]


def test_transcript_drops_messages_older_than_48h(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_input_event(connection, "evt-old", now, "vieux message", hours_ago=49)
        _insert_turn_reply(connection, "turn-old", "evt-old", "vieille reponse")
        _insert_input_event(connection, "evt-new", now, "message frais", hours_ago=1)
        _insert_turn_reply(connection, "turn-new", "evt-new", "reponse fraiche")
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now)

    assert [entry.text for entry in snapshot.recent_transcript] == ["message frais", "reponse fraiche"]


def test_transcript_excludes_current_event_and_foreign_user(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_input_event(connection, "evt-prev", now, "tour precedent", hours_ago=2)
        _insert_turn_reply(connection, "turn-prev", "evt-prev", "reponse precedente")
        _insert_input_event(connection, "evt-current", now, "tour courant", hours_ago=0)
        connection.execute(
            "insert into v0_input_events (id, user_id, source, type, text, payload_json, occurred_at)"
            " values ('evt-autre', 2, 'test', 'user_message', 'autre user', '{}', ?)",
            ((now - timedelta(hours=1)).isoformat(),),
        )
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now, current_event_id="evt-current")

    assert [entry.text for entry in snapshot.recent_transcript] == ["tour precedent", "reponse precedente"]


def test_header_renders_recent_conversation_clipped(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_input_event(connection, "evt-a", now, "x" * 400, hours_ago=2)
        _insert_turn_reply(connection, "turn-a", "evt-a", "reponse courte")
        connection.commit()

    text = SnapshotBuilder(db_path).build(user_id=1, now=now).header().to_prompt_text()

    assert "recent_conversation:" in text
    assert "user: " + "x" * 299 + "…" in text
    assert "coach: reponse courte" in text
    assert "[12/06 10:00]" in text


def test_header_omits_recent_conversation_when_empty(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)

    text = SnapshotBuilder(db_path).build(user_id=1, now=now).header().to_prompt_text()

    assert "recent_conversation" not in text


def test_header_word_budget_holds_with_full_transcript(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    long_message = " ".join(["mot"] * 80)
    with connect(db_path) as connection:
        for offset in (0, 1, 2, 14):
            _insert_session(connection, now, offset)
        for index in range(4):
            _insert_input_event(connection, f"evt-{index}", now, long_message, hours_ago=4 - index)
            _insert_turn_reply(connection, f"turn-{index}", f"evt-{index}", long_message)
        connection.commit()

    text = SnapshotBuilder(db_path).build(user_id=1, now=now).header().to_prompt_text()

    assert "recent_conversation:" in text  # l'assert interne <= 900 mots n'a pas sauté


def test_header_word_budget_holds_with_dense_short_tokens(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    dense_message = "a " * 200
    with connect(db_path) as connection:
        for index in range(4):
            _insert_input_event(connection, f"evt-{index}", now, dense_message, hours_ago=4 - index)
            _insert_turn_reply(connection, f"turn-{index}", f"evt-{index}", dense_message)
        connection.commit()

    text = SnapshotBuilder(db_path).build(user_id=1, now=now).header().to_prompt_text()

    assert "recent_conversation:" in text  # l'assert interne <= 900 mots n'a pas sauté


def test_transcript_user_message_without_reply_stands_alone(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_input_event(connection, "evt-crash", now, "message sans reponse", hours_ago=3)
        _insert_input_event(connection, "evt-nosend", now, "message no_send", hours_ago=2)
        _insert_turn_reply(connection, "turn-nosend", "evt-nosend", "")
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now)

    assert [(entry.role, entry.text) for entry in snapshot.recent_transcript] == [
        ("user", "message sans reponse"),
        ("user", "message no_send"),
    ]
