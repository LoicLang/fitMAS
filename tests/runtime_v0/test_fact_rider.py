from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.agent import CoachAgent
from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.policy import (
    SetSessionStatusCommand,
    RuntimePolicy,
    UpsertMemoryFactCommand,
)
from fitmas.runtime_v0.proposals import (
    ActionProposal,
    ExecutionUpdateDraft,
    MemoryFactDraft,
)
from fitmas.runtime_v0.snapshot import SessionView, SnapshotBuilder, WorldSnapshot
from fitmas.runtime_v0.state import ConversationState
from fitmas.runtime_v0.tool_catalog import for_event
from fitmas.runtime_v0.tools_read import ToolContext

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)


# ---------- agent merge ----------

def _agent_ctx(tmp_path) -> tuple[InputEvent, ToolContext]:
    event = InputEvent(
        id="evt-1", user_id=1, source="test", type="user_message",
        text="pas dispo + note", payload={}, occurred_at=NOW,
    )
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_scheduled_sessions (id, user_id, date, sport, title, duration_min, "
            "intensity_label, priority, status) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (66, 1, "2026-05-22", "run", "Footing", 45, "easy", "secondary", "planned"),
        )
        connection.commit()
    snapshot = SnapshotBuilder(db_path).build(1, NOW)
    return event, ToolContext(db_path=db_path, snapshot=snapshot, scratchpad={})


def test_memory_and_action_merge_into_one_proposal(tmp_path):
    event, ctx = _agent_ctx(tmp_path)
    client = FakeLLMClient([
        LLMResponse(tool_calls=(
            ToolCall(name="propose_memory_update", args={"kind": "health", "text": "mal au genou", "confidence": 0.9}),
            ToolCall(name="propose_execution_update", args={"session_id": 66, "status": "skipped", "evidence": "x"}),
        ))
    ])
    proposal = CoachAgent(client, "system").run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "execution_update"
    assert proposal.execution_update is not None and proposal.execution_update.session_id == 66
    assert len(proposal.memory_updates) == 1
    assert proposal.memory_updates[0].kind == "health"


def test_memory_rider_works_regardless_of_call_order(tmp_path):
    event, ctx = _agent_ctx(tmp_path)
    client = FakeLLMClient([
        LLMResponse(tool_calls=(
            ToolCall(name="propose_execution_update", args={"session_id": 66, "status": "skipped", "evidence": "x"}),
            ToolCall(name="propose_memory_update", args={"kind": "availability", "text": "indispo 3j", "confidence": 0.8}),
        ))
    ])
    proposal = CoachAgent(client, "system").run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "execution_update"
    assert len(proposal.memory_updates) == 1
    assert proposal.memory_updates[0].kind == "availability"


def test_memory_update_alone_is_unchanged(tmp_path):
    event, ctx = _agent_ctx(tmp_path)
    client = FakeLLMClient([
        LLMResponse(tool_calls=(
            ToolCall(name="propose_memory_update", args={"kind": "health", "text": "mal au genou", "confidence": 0.9}),
        ))
    ])
    proposal = CoachAgent(client, "system").run(event, ctx.snapshot.header(), for_event(event, ctx.snapshot), tool_context=ctx)

    assert proposal.type == "memory_update"
    assert len(proposal.memory_updates) == 1


# ---------- policy rider ----------

def _snapshot_with_session() -> WorldSnapshot:
    session = SessionView(
        id=66, date=date(2026, 5, 21), sport="run", title="Footing",
        duration_min=45, intensity_label="easy", priority="secondary", status="planned",
    )
    return WorldSnapshot(
        user_id=1, today=NOW.date(), now=NOW, timezone="Europe/Paris", objective=None,
        current_plan=(), recent_plan=(session,), recent_activities=(),
        active_facts=(), active_pending=None, recent_execution_events=(),
        recent_plan_events=(), conversation_state=ConversationState(None, None, None, None, None),
    )


def _execution_proposal(memory: tuple[MemoryFactDraft, ...]) -> ActionProposal:
    return ActionProposal(
        type="execution_update",
        confidence=0.8,
        user_intent_summary="note + skip",
        evidence=("x",),
        execution_update=ExecutionUpdateDraft(session_id=66, status="skipped", evidence="x"),
        memory_updates=memory,
    )


def test_policy_rider_prepends_fact_to_action():
    proposal = _execution_proposal((MemoryFactDraft(kind="availability", text="indispo 3j", confidence=0.8, expires_at=None),))
    decision = RuntimePolicy().evaluate(proposal, _snapshot_with_session())

    assert decision.action == "allow_commit"
    kinds = [type(c).__name__ for c in decision.commands]
    assert kinds == ["UpsertMemoryFactCommand", "SetSessionStatusCommand"]


def test_policy_rider_invalid_fact_blocks():
    proposal = _execution_proposal((MemoryFactDraft(kind="not_a_kind", text="x", confidence=0.8, expires_at=None),))
    decision = RuntimePolicy().evaluate(proposal, _snapshot_with_session())

    assert decision.action == "block"
    assert decision.reason == "invalid_fact_kind"


def test_policy_memory_update_alone_unchanged():
    proposal = ActionProposal(
        type="memory_update", confidence=0.9, user_intent_summary="note",
        evidence=("mal au genou",),
        memory_updates=(MemoryFactDraft(kind="health", text="mal au genou", confidence=0.9, expires_at=None),),
    )
    decision = RuntimePolicy().evaluate(proposal, _snapshot_with_session())

    assert decision.action == "allow_commit"
    assert [type(c).__name__ for c in decision.commands] == ["UpsertMemoryFactCommand"]
