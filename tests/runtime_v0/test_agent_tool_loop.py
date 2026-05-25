from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.agent import CoachAgent
from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall, ToolSchema
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.snapshot import SnapshotBuilder
from fitmas.runtime_v0.tool_catalog import for_event
from fitmas.runtime_v0.tools_read import ToolContext


PARIS = ZoneInfo("Europe/Paris")


def _event(text: str = "Redonne-moi le plan actuel.") -> InputEvent:
    return InputEvent(
        id="evt-1",
        user_id=1,
        source="test",
        type="user_message",
        text=text,
        payload={},
        occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=PARIS),
    )


def _context(tmp_path, event: InputEvent) -> ToolContext:
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
            (66, 1, "2026-05-22", "run", "Footing recup", 45, "easy", "secondary", "planned"),
        )
        connection.commit()
    snapshot = SnapshotBuilder(db_path).build(1, event.occurred_at)
    return ToolContext(db_path=db_path, snapshot=snapshot, scratchpad={})


def test_direct_text_after_read_tool_becomes_answer_with_read_facts(tmp_path):
    event = _event()
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(text="Aujourd'hui: Footing recup."),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(
        event=event,
        snapshot_header=ctx.snapshot.header(),
        tools=for_event(event, ctx.snapshot),
        tool_context=ctx,
    )

    assert proposal.type == "answer"
    assert "Footing recup" in proposal.answer_facts[0]
    assert ctx.scratchpad["calls"][0] == {"name": "get_current_plan", "ok": True}


def test_direct_plan_answer_without_read_support_is_no_send(tmp_path):
    event = _event("J'ai quoi demain exactement ?")
    ctx = _context(tmp_path, event)
    client = FakeLLMClient([LLMResponse(text="Demain tu cours 45 minutes.")])
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "no_send"
    assert proposal.user_intent_summary == "missing_read_support"


def test_incidental_read_tool_is_not_enough_for_plan_answer_and_gets_retry(tmp_path):
    event = _event("J'ai quoi demain exactement ?")
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="get_active_facts", args={}),)),
            LLMResponse(text="Demain tu cours 45 minutes."),
            LLMResponse(tool_calls=(ToolCall(name="get_plan_day", args={"date": "2026-05-22"}),)),
            LLMResponse(text="Aujourd'hui: Footing recup."),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx, max_steps=4)

    assert proposal.type == "answer"
    assert proposal.tool_trace == (
        {"name": "get_active_facts", "ok": True},
        {"name": "get_plan_day", "ok": True},
    )
    assert [request["messages"][-1]["tool_name"] for request in client.requests[2:3]] == [
        "runtime_contract"
    ]


def test_unknown_tool_gets_one_retry_then_can_answer(tmp_path):
    event = _event()
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="missing_tool", args={}),)),
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(text="Plan lu."),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "answer"
    assert len(client.requests) == 3


def test_invalid_tool_args_get_one_retry_then_can_answer(tmp_path):
    event = _event()
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="get_plan_day", args={"date": "not-a-date"}),)),
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(text="Plan lu."),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "answer"
    assert ctx.scratchpad["calls"][0] == {"name": "get_plan_day", "ok": False}
    assert ctx.scratchpad["calls"][1] == {"name": "get_current_plan", "ok": True}


def test_invalid_proposal_args_get_one_retry_then_can_commit_proposal(tmp_path):
    event = _event("J'ai pas fait hier.")
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="propose_execution_update", args={"session_id": 66}),)),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="propose_execution_update",
                        args={"session_id": 66, "status": "skipped", "evidence": "pas fait"},
                    ),
                )
            ),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "execution_update"
    assert proposal.execution_update is not None
    assert proposal.execution_update.status == "skipped"
    assert "invalid_tool_args" in client.requests[1]["messages"][-1]["content"]


def test_first_proposal_tool_wins(tmp_path):
    event = _event("J'ai pas fait hier.")
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="propose_execution_update",
                        args={"session_id": 66, "status": "skipped", "evidence": "user said skipped"},
                    ),
                    ToolCall(
                        name="ask_clarification",
                        args={"question": "Quelle seance ?"},
                    ),
                )
            )
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "execution_update"
    assert proposal.execution_update is not None
    assert proposal.execution_update.session_id == 66
    assert len(ctx.scratchpad["calls"]) == 1


def test_mixed_read_and_proposal_calls_execute_read_before_proposal(tmp_path):
    event = _event("Décale ça à vendredi.")
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(name="resolve_date_reference", args={"weekday": "friday", "direction": "future"}),
                    ToolCall(
                        name="ask_clarification",
                        args={
                            "question": "Quelle séance veux-tu déplacer ?",
                            "unresolved_intent": {
                                "type": "move_session",
                                "target_date": "2026-05-29",
                                "missing": ["source_ref"],
                            },
                        },
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="ask_clarification",
                        args={
                            "question": "Quelle séance veux-tu déplacer ?",
                            "unresolved_intent": {
                                "type": "move_session",
                                "target_date": "2026-05-29",
                                "missing": ["source_ref"],
                            },
                        },
                    ),
                )
            ),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "ask_clarification"
    assert proposal.unresolved_intent["target_date"] == "2026-05-29"
    assert ctx.scratchpad["calls"] == [
        {"name": "resolve_date_reference", "ok": True},
        {"name": "ask_clarification", "ok": True},
    ]
    assert len(client.requests) == 1


def test_active_move_intent_accepts_get_session_and_plan_patch_in_same_response(tmp_path):
    event = _event("Je parle de la séance de récup.")
    ctx = _context(tmp_path, event)
    header = replace(
        ctx.snapshot.header(),
        last_unresolved_intent={"type": "move_session", "target_date": "2026-05-29", "missing": ["source_ref"]},
    )
    client = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(name="get_session", args={"session_id": 66}),
                    ToolCall(
                        name="propose_plan_patch",
                        args={
                            "operations": [{"kind": "move", "source_session_id": 66, "target_date": "2026-05-29"}],
                            "rationale": "déplacer la récup à vendredi",
                        },
                    ),
                )
            ),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, header, for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "plan_patch"
    assert proposal.plan_patch is not None
    assert ctx.scratchpad["calls"] == [
        {"name": "get_session", "ok": True},
        {"name": "propose_plan_patch", "ok": True},
    ]


def test_plan_patch_without_exact_source_read_gets_contract_retry(tmp_path):
    event = _event("Décale ça à vendredi.")
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="resolve_date_reference", args={"weekday": "friday", "direction": "future"}),)),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="propose_plan_patch",
                        args={
                            "operations": [
                                {
                                    "kind": "move",
                                    "source_session_id": 66,
                                    "target_date": "2026-05-29",
                                }
                            ],
                            "rationale": "move",
                        },
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="ask_clarification",
                        args={
                            "question": "Quelle séance veux-tu déplacer ?",
                            "unresolved_intent": {
                                "type": "move_session",
                                "target_date": "2026-05-29",
                                "missing": ["source_ref"],
                            },
                        },
                    ),
                )
            ),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "ask_clarification"
    assert proposal.unresolved_intent == {
        "type": "move_session",
        "target_date": "2026-05-29",
        "missing": ["source_ref"],
    }
    assert client.requests[2]["messages"][-1]["tool_name"] == "runtime_contract"


def test_move_clarification_with_target_date_requires_date_resolution_tool(tmp_path):
    event = _event("Décale ça à vendredi.")
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="ask_clarification",
                        args={
                            "question": "Quelle séance veux-tu déplacer ?",
                            "unresolved_intent": {
                                "type": "move_session",
                                "target_date": "2026-05-23",
                                "missing": ["source_ref"],
                            },
                        },
                    ),
                )
            ),
            LLMResponse(tool_calls=(ToolCall(name="resolve_date_reference", args={"weekday": "friday", "direction": "future"}),)),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="ask_clarification",
                        args={
                            "question": "Quelle séance veux-tu déplacer ?",
                            "unresolved_intent": {
                                "type": "move_session",
                                "target_date": "2026-05-29",
                                "missing": ["source_ref"],
                            },
                        },
                    ),
                )
            ),
        ]
    )

    proposal = CoachAgent(client, system_prompt="system").run(
        event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx
    )

    assert proposal.type == "ask_clarification"
    assert proposal.unresolved_intent["target_date"] == "2026-05-29"
    assert ctx.scratchpad["calls"] == [
        {"name": "ask_clarification", "ok": True},
        {"name": "resolve_date_reference", "ok": True},
        {"name": "ask_clarification", "ok": True},
    ]
    assert client.requests[1]["messages"][-1]["tool_name"] == "runtime_contract"


def test_text_after_date_resolution_retries_with_planning_proposal_contract(tmp_path):
    event = _event("Décale ça à vendredi.")
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="resolve_date_reference", args={"weekday": "friday", "direction": "future"}),)),
            LLMResponse(text="Vendredi résolu."),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="ask_clarification",
                        args={
                            "question": "Quelle séance veux-tu déplacer ?",
                            "unresolved_intent": {
                                "type": "move_session",
                                "target_date": "2026-05-29",
                                "missing": ["source_ref"],
                            },
                        },
                    ),
                )
            ),
        ]
    )

    proposal = CoachAgent(client, system_prompt="system").run(
        event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx
    )

    assert proposal.type == "ask_clarification"
    retry_payload = client.requests[2]["messages"][-1]["content"]
    assert "planning_date_resolution_requires_proposal" in retry_payload


def test_active_move_intent_retries_execution_update_as_wrong_contract(tmp_path):
    event = _event("Je parle de la séance de récup.")
    ctx = _context(tmp_path, event)
    header = replace(
        ctx.snapshot.header(),
        last_unresolved_intent={"type": "move_session", "target_date": "2026-05-29", "missing": ["source_ref"]},
    )
    client = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(name="propose_execution_update", args={"session_id": 66, "status": "done"}),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="ask_clarification",
                        args={
                            "question": "Quelle séance veux-tu déplacer ?",
                            "unresolved_intent": {
                                "type": "move_session",
                                "target_date": "2026-05-29",
                                "missing": ["source_ref"],
                            },
                        },
                    ),
                )
            ),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, header, for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "ask_clarification"
    assert client.requests[1]["messages"][-1]["tool_name"] == "runtime_contract"


def test_active_move_intent_retries_direct_text_answer_as_wrong_contract(tmp_path):
    event = _event("Je parle de la séance de récup.")
    ctx = _context(tmp_path, event)
    header = replace(
        ctx.snapshot.header(),
        last_unresolved_intent={"type": "move_session", "target_date": "2026-05-29", "missing": ["source_ref"]},
    )
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="get_session", args={"session_id": 66}),)),
            LLMResponse(text="La séance de récup est le 22."),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        name="propose_plan_patch",
                        args={
                            "operations": [{"kind": "move", "source_session_id": 66, "target_date": "2026-05-29"}],
                            "rationale": "déplacer la séance de récup à vendredi",
                        },
                    ),
                )
            ),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, header, for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "plan_patch"
    assert client.requests[2]["messages"][-1]["tool_name"] == "runtime_contract"


def test_max_steps_without_answer_or_proposal_returns_no_send(tmp_path):
    event = _event()
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
        ]
    )
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx, max_steps=3)

    assert proposal.type == "no_send"
    assert proposal.user_intent_summary == "max_steps_reached"


def test_agent_default_max_steps_is_three(tmp_path):
    event = _event()
    ctx = _context(tmp_path, event)
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(tool_calls=(ToolCall(name="get_current_plan", args={"days": 7}),)),
            LLMResponse(text="too late"),
        ]
    )

    proposal = CoachAgent(client, system_prompt="system").run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "no_send"
    assert proposal.user_intent_summary == "max_steps_reached"
    assert len(client.requests) == 3


def test_agent_can_run_tools_without_tool_context_for_unit_handlers(tmp_path):
    event = _event()
    client = FakeLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(name="unit_read", args={"value": "ok"}),)),
            LLMResponse(text="ok"),
        ]
    )
    tool = ToolSchema(
        name="unit_read",
        description="unit",
        parameters={},
        handler=lambda value: {"value": value},
        is_proposal=False,
    )
    ctx = _context(tmp_path, event)
    agent = CoachAgent(client, system_prompt="system")

    proposal = agent.run(event, ctx.snapshot.header(), (tool,))

    assert proposal.type == "answer"
    assert proposal.answer_facts == ('{"value": "ok"}',)
