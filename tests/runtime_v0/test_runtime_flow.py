from __future__ import annotations

from datetime import datetime
import json
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.audit import load_turn
from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event


PARIS = ZoneInfo("Europe/Paris")


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
        coach_llm=FakeLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
                LLMResponse(text="Aujourd'hui: Footing."),
            ]
        ),
        reply_llm=FakeLLMClient([LLMResponse(text="Aujourd'hui: Footing.")]),
    )

    result = handle_event(event, deps=deps, turn_id="turn-user")
    turn = load_turn(db_path, "turn-user")

    assert result.reply == "Aujourd'hui: Footing."
    assert result.runtime_result.proposal_type == "answer"
    assert result.guard.ok
    assert turn is not None
    proposal_json = json.loads(turn["proposal_json"])
    result_json = json.loads(turn["result_json"])
    assert proposal_json["tool_trace"] == [{"name": "get_current_plan", "ok": True}]
    assert result_json["policy_action"] == "answer_only"
    assert result_json["read_facts"]


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
