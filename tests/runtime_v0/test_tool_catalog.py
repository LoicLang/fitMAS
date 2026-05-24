from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.prompts.coach_system import COACH_SYSTEM_PROMPT
from fitmas.runtime_v0.snapshot import SnapshotBuilder
from fitmas.runtime_v0.tool_catalog import for_event


PARIS = ZoneInfo("Europe/Paris")


def _event(event_type: str = "user_message") -> InputEvent:
    return InputEvent(
        id="evt-1",
        user_id=1,
        source="test",
        type=event_type,
        text="Redonne-moi le plan actuel.",
        payload={},
        occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=PARIS),
    )


def test_user_message_gets_all_ten_v0_tools(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    event = _event()
    snapshot = SnapshotBuilder(db_path).build(1, event.occurred_at)

    tools = for_event(event, snapshot)

    assert {tool.name for tool in tools} == {
        "get_current_plan",
        "get_plan_day",
        "get_session",
        "get_recent_execution_events",
        "get_active_facts",
        "propose_execution_update",
        "propose_execution_correction",
        "propose_plan_patch",
        "propose_memory_update",
        "ask_clarification",
    }
    assert all(callable(tool.handler) for tool in tools)
    assert all(tool.parameters.get("type") == "object" for tool in tools)
    assert all("properties" in tool.parameters for tool in tools)
    clarification = next(tool for tool in tools if tool.name == "ask_clarification")
    assert "unresolved_intent" in clarification.parameters["required"]
    plan_patch = next(tool for tool in tools if tool.name == "propose_plan_patch")
    operation = plan_patch.parameters["properties"]["operations"]["items"]
    assert {"kind", "source_session_id", "target_date"} <= set(operation["properties"])


def test_reserved_events_get_no_tools_in_v0(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    event = _event("heartbeat_tick")
    snapshot = SnapshotBuilder(db_path).build(1, event.occurred_at)

    assert for_event(event, snapshot) == ()


def test_active_move_intent_gets_plan_scoped_tools(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    event = _event()
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_conversation_state (user_id, last_unresolved_intent_json) values (?, ?)",
            (1, json.dumps({"type": "move_session", "target_date": "2026-05-29"})),
        )
        connection.commit()
    snapshot = SnapshotBuilder(db_path).build(1, event.occurred_at)

    assert {tool.name for tool in for_event(event, snapshot)} == {
        "get_current_plan",
        "get_plan_day",
        "get_session",
        "propose_plan_patch",
        "ask_clarification",
    }


def test_fake_llm_client_returns_scripted_responses_and_records_calls():
    first = LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),))
    second = LLMResponse(text="Plan lu.")
    client = FakeLLMClient([first, second])

    assert client.chat_with_tools("system", [{"role": "user", "content": "plan"}], []) is first
    assert client.chat_with_tools("system", [{"role": "user", "content": "merci"}], []) is second
    assert len(client.requests) == 2
    assert client.requests[0]["system"] == "system"

    with pytest.raises(RuntimeError, match="no_scripted_response"):
        client.chat_with_tools("system", [], [])


def test_coach_prompt_keeps_followup_target_date_without_reconfirming():
    assert "source_ref" in COACH_SYSTEM_PROMPT
    assert "propose_plan_patch sans redemander la date" in COACH_SYSTEM_PROMPT
