from __future__ import annotations

from datetime import datetime, timedelta
import json
import time
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.audit import load_turn
from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event


PARIS = ZoneInfo("Europe/Paris")


class SlowFakeLLMClient(FakeLLMClient):
    def chat_with_tools(self, system, messages, tools):
        time.sleep(0.002)
        return super().chat_with_tools(system, messages, tools)


def _event(event_type: str = "user_message", text: str | None = "Plan actuel ?") -> InputEvent:
    return InputEvent(
        id=f"evt-{event_type}",
        user_id=1,
        source="test",
        type=event_type,
        text=text,
        payload={},
        occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=PARIS),
    )


def _seed_session(db_path):
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
        connection.commit()


def _seed_key_session(db_path):
    with connect(db_path) as connection:
        connection.execute(
            """
            insert into v0_scheduled_sessions (
                id, user_id, date, sport, title, duration_min,
                intensity_label, priority, status
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (61, 1, "2026-05-23", "run", "VMA", 45, "hard", "key", "planned"),
        )
        connection.commit()


def test_unsupported_event_returns_no_send_and_audits_turn(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    event = _event("heartbeat_tick", text=None)
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient([]),
        reply_llm=FakeLLMClient([]),
    )

    result = handle_event(event, deps=deps, turn_id="turn-unsupported")
    turn = load_turn(db_path, "turn-unsupported")

    assert result.reply == ""
    assert result.runtime_result.policy_action == "no_send"
    assert turn is not None
    assert json.loads(turn["proposal_json"])["type"] == "no_send"
    assert json.loads(turn["result_json"])["policy_action"] == "no_send"


def test_user_message_runs_full_fake_flow_and_audits_tool_trace(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_session(db_path)
    event = _event()
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=SlowFakeLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
                LLMResponse(text="Aujourd'hui: Footing."),
            ]
        ),
        reply_llm=SlowFakeLLMClient([LLMResponse(text="Aujourd'hui: Footing.")]),
    )

    result = handle_event(event, deps=deps, turn_id="turn-user")
    turn = load_turn(db_path, "turn-user")

    assert result.reply == "Aujourd'hui: Footing."
    assert result.runtime_result.proposal_type == "answer"
    assert result.guard.ok
    assert turn is not None
    proposal_json = json.loads(turn["proposal_json"])
    result_json = json.loads(turn["result_json"])
    snapshot_json = json.loads(turn["snapshot_json"])
    assert proposal_json["tool_trace"] == [{"name": "get_current_plan", "ok": True}]
    assert result_json["policy_action"] == "answer_only"
    assert result_json["read_facts"]
    assert snapshot_json["current_plan"][0]["id"] == 60
    assert result_json["reply_attempts"] == 1
    assert result_json["guard_repair_used"] is False


def test_same_event_id_reuses_existing_turn_and_does_not_write_twice(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_session(db_path)
    event = _event(text="J'ai pas fait la séance.")
    first_deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=SlowFakeLLMClient(
            [LLMResponse(tool_calls=(ToolCall(name="propose_execution_update", args={"session_id": 60, "status": "skipped"}),))]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="Noté pour la séance.")]),
    )
    second_deps = RuntimeDeps(db_path=db_path, coach_llm=FakeLLMClient([]), reply_llm=FakeLLMClient([]))

    first = handle_event(event, deps=first_deps, turn_id="turn-first")
    second = handle_event(event, deps=second_deps, turn_id="turn-second")

    with connect(db_path) as connection:
        turns = connection.execute("select id from v0_turns order by id").fetchall()
        command_count = connection.execute("select count(*) from v0_command_events").fetchone()[0]
    assert first.turn_id == second.turn_id == "turn-first"
    assert first.reply == second.reply
    assert [row["id"] for row in turns] == ["turn-first"]
    assert command_count == 1


def test_existing_event_lock_with_incomplete_turn_returns_processing_without_llm(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_session(db_path)
    event = _event()
    with connect(db_path) as connection:
        connection.execute("insert into v0_idempotency_locks (event_id, turn_id) values (?, ?)", (event.id, "turn-locked"))
        connection.execute("insert into v0_turns (id) values (?)", ("turn-locked",))
        connection.commit()
    coach_llm = FakeLLMClient([])
    reply_llm = FakeLLMClient([])
    deps = RuntimeDeps(db_path=db_path, coach_llm=coach_llm, reply_llm=reply_llm)

    result = handle_event(event, deps=deps, turn_id="ignored-turn")

    assert result.turn_id == "turn-locked"
    assert result.reply == ""
    assert result.proposal.user_intent_summary == "processing"
    assert result.runtime_result.policy_action == "no_send"
    assert coach_llm.requests == []
    assert reply_llm.requests == []


def test_failed_event_lock_retries_same_turn_and_completes(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_session(db_path)
    event = _event()
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_idempotency_locks (event_id, turn_id, status) values (?, ?, ?)",
            (event.id, "turn-retry", "failed"),
        )
        connection.execute("insert into v0_turns (id) values (?)", ("turn-retry",))
        connection.commit()
    coach_llm = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(text="Aujourd'hui: Footing."),
        ]
    )
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=coach_llm,
        reply_llm=FakeLLMClient([LLMResponse(text="Aujourd'hui: Footing.")]),
    )

    result = handle_event(event, deps=deps, turn_id="ignored-turn")

    with connect(db_path) as connection:
        lock = connection.execute("select status from v0_idempotency_locks where event_id = ?", (event.id,)).fetchone()
    assert result.turn_id == "turn-retry"
    assert result.reply == "Aujourd'hui: Footing."
    assert len(coach_llm.requests) == 2
    assert lock["status"] == "completed"


def test_stale_running_event_lock_retries_same_turn(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_session(db_path)
    event = _event()
    stale_time = (event.occurred_at - timedelta(minutes=20)).replace(tzinfo=None).isoformat(sep=" ")
    with connect(db_path) as connection:
        connection.execute(
            """
            insert into v0_idempotency_locks (event_id, turn_id, status, updated_at)
            values (?, ?, ?, ?)
            """,
            (event.id, "turn-stale", "running", stale_time),
        )
        connection.execute("insert into v0_turns (id) values (?)", ("turn-stale",))
        connection.commit()
    coach_llm = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(text="Aujourd'hui: Footing."),
        ]
    )
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=coach_llm,
        reply_llm=FakeLLMClient([LLMResponse(text="Aujourd'hui: Footing.")]),
    )

    result = handle_event(event, deps=deps, turn_id="ignored-turn")

    with connect(db_path) as connection:
        lock = connection.execute("select status from v0_idempotency_locks where event_id = ?", (event.id,)).fetchone()
        turn_count = connection.execute("select count(*) from v0_turns where id = ?", ("turn-stale",)).fetchone()[0]
    assert result.turn_id == "turn-stale"
    assert result.reply == "Aujourd'hui: Footing."
    assert len(coach_llm.requests) == 2
    assert lock["status"] == "completed"
    assert turn_count == 1


def test_persisted_turn_records_real_latency_and_completes_lock(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_session(db_path)
    event = _event()
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
                LLMResponse(text="Aujourd'hui: Footing."),
            ]
        ),
        reply_llm=SlowFakeLLMClient([LLMResponse(text="Aujourd'hui: Footing.")]),
    )

    handle_event(event, deps=deps, turn_id="turn-latency")

    turn = load_turn(db_path, "turn-latency")
    with connect(db_path) as connection:
        lock = connection.execute("select status from v0_idempotency_locks where event_id = ?", (event.id,)).fetchone()
    assert turn["latency_ms"] > 0
    assert lock["status"] == "completed"


def test_pending_command_is_loaded_into_runtime_result(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_key_session(db_path)
    event = _event(text="Décale la VMA à vendredi.")
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall(name="resolve_date_reference", args={"weekday": "friday", "direction": "future"}),)),
                LLMResponse(tool_calls=(ToolCall(name="get_session", args={"session_id": 61}),)),
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            name="propose_plan_patch",
                            args={
                                "operations": [{"kind": "move", "source_session_id": 61, "target_date": "2026-05-29"}],
                                "rationale": "déplacer la VMA à vendredi",
                            },
                        ),
                    )
                ),
            ]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="Je dois confirmer avant de faire ça: déplacer la VMA à vendredi.")]),
    )

    result = handle_event(event, deps=deps, turn_id="turn-pending")

    assert result.runtime_result.policy_action == "create_pending"
    assert result.runtime_result.pending is not None
    assert result.runtime_result.pending.summary == "déplacer la VMA à vendredi"
    assert result.runtime_result.reply_contract.tone == "asking"


def test_guarded_reply_gets_one_llm_repair_retry(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_session(db_path)
    event = _event()
    reply_llm = FakeLLMClient(
        [
            LLMResponse(text="runtime 22 Footing 2026-05-24"),
            LLMResponse(text="Aujourd'hui: Footing."),
        ]
    )
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
                LLMResponse(text="Aujourd'hui: Footing."),
            ]
        ),
        reply_llm=reply_llm,
    )

    result = handle_event(event, deps=deps, turn_id="turn-retry")

    assert result.reply == "Aujourd'hui: Footing."
    assert result.guard.ok
    assert len(reply_llm.requests) == 2
    assert "Erreurs:" in reply_llm.requests[1]["system"]
    turn = load_turn(db_path, "turn-retry")
    result_json = json.loads(turn["result_json"])
    assert result_json["reply_attempts"] == 2
    assert result_json["guard_repair_used"] is True


def test_propose_then_confirm_commits_week(tmp_path):
    from datetime import datetime, timezone
    from fitmas.runtime_v0.db import connect, init_db
    from fitmas.runtime_v0.event import InputEvent
    from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
    from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
    from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)  # Thursday
    good_week = [
        {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard"},
        {"date": "2026-06-11", "type": "easy_run", "duration_min": 60, "intensity": "easy"},
        {"date": "2026-06-13", "type": "easy_run", "duration_min": 50, "intensity": "easy"},
        {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate"},
    ]
    coach = FakeLLMClient([
        LLMResponse(tool_calls=(ToolCall(name="propose_week", args={"last_week_load": 300.0, "key_type": "threshold"}),)),
        LLMResponse(tool_calls=(ToolCall(name="resolve_pending", args={"pending_id": 1, "decision": "accept"}),)),
    ])
    generation = FakeLLMClient([LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": good_week}),))])
    reply = FakeLLMClient([
        LLMResponse(text="Voici ta semaine du 8 juin, je cale ?"),
        LLMResponse(text="C'est calé, ta semaine du 8 juin est validée."),
    ])
    deps = RuntimeDeps(db_path=db_path, coach_llm=coach, reply_llm=reply, generation_llm=generation)

    e1 = InputEvent(id="e1", user_id=1, source="test", type="user_message", text="fais-moi ma semaine prochaine", payload={}, occurred_at=now)
    r1 = handle_event(e1, deps, turn_id="turn-1")
    assert r1.policy.action == "create_pending"
    with connect(db_path) as connection:
        pending = connection.execute("select id, status from v0_pending_confirmations").fetchone()
        week_count = connection.execute("select count(*) from v0_planned_weeks").fetchone()[0]
    assert pending["status"] == "open"
    assert week_count == 0  # nothing committed yet

    e2 = InputEvent(id="e2", user_id=1, source="test", type="user_message", text="oui", payload={}, occurred_at=now)
    r2 = handle_event(e2, deps, turn_id="turn-2")
    assert r2.policy.action == "allow_commit"
    with connect(db_path) as connection:
        week = connection.execute("select * from v0_planned_weeks").fetchone()
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert week["week_start"] == "2026-06-08"
    assert week["key_type"] == "threshold"
    assert pending["status"] == "accepted"
    assert r2.guard.ok


def test_next_turn_snapshot_sees_previous_exchange(tmp_path):
    from fitmas.runtime_v0.snapshot import SnapshotBuilder
    from fitmas.runtime_v0.llm_clients.base import LLMResponse

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_session(db_path)
    first = InputEvent(
        id="evt-fil-1", user_id=1, source="test", type="user_message",
        text="Tu peux deplacer ma seance a demain ?", payload={},
        occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=PARIS),
    )
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient([LLMResponse(text="Je décale ta séance à demain.")]),
        reply_llm=FakeLLMClient([LLMResponse(text="C'est noté, ta séance est déplacée à demain.")]),
    )
    handle_event(first, deps=deps, turn_id="turn-fil-1")

    snapshot = SnapshotBuilder(db_path).build(
        user_id=1,
        now=datetime(2026, 5, 22, 14, 5, tzinfo=PARIS),
        current_event_id="evt-fil-2",
    )

    assert any(
        entry.role == "user" and entry.text == "Tu peux deplacer ma seance a demain ?"
        for entry in snapshot.recent_transcript
    )


def test_propose_then_reject_drops_week(tmp_path):
    from datetime import datetime, timezone
    from fitmas.runtime_v0.db import connect, init_db
    from fitmas.runtime_v0.event import InputEvent
    from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
    from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
    from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    good_week = [
        {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard"},
        {"date": "2026-06-11", "type": "easy_run", "duration_min": 60, "intensity": "easy"},
        {"date": "2026-06-13", "type": "easy_run", "duration_min": 50, "intensity": "easy"},
        {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate"},
    ]
    coach = FakeLLMClient([
        LLMResponse(tool_calls=(ToolCall(name="propose_week", args={"last_week_load": 300.0, "key_type": "threshold"}),)),
        LLMResponse(tool_calls=(ToolCall(name="resolve_pending", args={"pending_id": 1, "decision": "reject"}),)),
    ])
    generation = FakeLLMClient([LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": good_week}),))])
    reply = FakeLLMClient([
        LLMResponse(text="Voici ta semaine du 8 juin, je cale ?"),
        LLMResponse(text="Ok, je laisse tomber cette semaine."),
    ])
    deps = RuntimeDeps(db_path=db_path, coach_llm=coach, reply_llm=reply, generation_llm=generation)

    handle_event(InputEvent(id="e1", user_id=1, source="test", type="user_message", text="fais-moi ma semaine", payload={}, occurred_at=now), deps, turn_id="turn-1")
    r2 = handle_event(InputEvent(id="e2", user_id=1, source="test", type="user_message", text="non", payload={}, occurred_at=now), deps, turn_id="turn-2")

    with connect(db_path) as connection:
        week_count = connection.execute("select count(*) from v0_planned_weeks").fetchone()[0]
        pending = connection.execute("select status from v0_pending_confirmations where id = 1").fetchone()
    assert week_count == 0
    assert pending["status"] == "rejected"
    assert r2.guard.ok
