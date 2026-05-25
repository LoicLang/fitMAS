from __future__ import annotations

from datetime import datetime
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
