from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.executor import CommandExecutor
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.policy import ResolveMemoryFactCommand, RuntimePolicy
from fitmas.runtime_v0.proposals import (
    ActionProposal,
    FactResolutionDraft,
    proposal_from_dict,
    proposal_to_dict,
)
from fitmas.runtime_v0.snapshot import (
    FactView,
    SnapshotBuilder,
    WorldSnapshot,
)
from fitmas.runtime_v0.state import ConversationState
from fitmas.runtime_v0 import tool_catalog
from fitmas.runtime_v0.tools_proposal import propose_fact_resolution
from fitmas.runtime_v0.tools_read import ToolContext

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 5, 22, 14, 0, tzinfo=PARIS)


def _insert_fact(connection, fact_id: int, *, expires_at: str | None = None) -> None:
    connection.execute(
        "insert into v0_facts (id, user_id, kind, text, confidence, created_at, expires_at) "
        "values (?, ?, ?, ?, ?, ?, ?)",
        (fact_id, 1, "health", "douleur genou", 0.9, "2026-05-20T09:00:00+02:00", expires_at),
    )


def _db(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    return db_path


def _fact_view(fact_id: int) -> FactView:
    return FactView(
        id=fact_id,
        kind="health",
        text="douleur genou",
        confidence=0.9,
        created_at=NOW - timedelta(days=2),
        expires_at=None,
    )


def _snapshot(facts: tuple[FactView, ...]) -> WorldSnapshot:
    return WorldSnapshot(
        user_id=1,
        today=NOW.date(),
        now=NOW,
        timezone="Europe/Paris",
        objective=None,
        current_plan=(),
        recent_plan=(),
        recent_activities=(),
        active_facts=facts,
        active_pending=None,
        recent_execution_events=(),
        recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )


# --- executor + snapshot lifecycle ---

def test_resolve_command_sets_resolved_at_and_snapshot_excludes(tmp_path):
    db_path = _db(tmp_path)
    with connect(db_path) as connection:
        _insert_fact(connection, 1)
        connection.commit()

    events = CommandExecutor(db_path).execute(
        (ResolveMemoryFactCommand(fact_id=1, reason="douleur passée"),),
        turn_id="t-resolve",
    )

    assert events[0].status == "applied"
    with connect(db_path) as connection:
        row = connection.execute("select resolved_at from v0_facts where id = 1").fetchone()
    assert row["resolved_at"] is not None

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=NOW)
    assert all(fact.id != 1 for fact in snapshot.active_facts)


def test_unresolved_fact_stays_active_in_snapshot(tmp_path):
    db_path = _db(tmp_path)
    with connect(db_path) as connection:
        _insert_fact(connection, 1)
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=NOW)
    assert any(fact.id == 1 for fact in snapshot.active_facts)


# --- policy ---

def test_policy_resolution_valid_id_allows_commit():
    proposal = ActionProposal(
        type="fact_resolution",
        confidence=0.9,
        user_intent_summary="resolution",
        evidence=("douleur passée",),
        fact_resolution=FactResolutionDraft(fact_id=1, reason="douleur passée"),
    )
    decision = RuntimePolicy().evaluate(proposal, _snapshot((_fact_view(1),)))

    assert decision.action == "allow_commit"
    assert len(decision.commands) == 1
    command = decision.commands[0]
    assert isinstance(command, ResolveMemoryFactCommand)
    assert command.fact_id == 1


def test_policy_resolution_unknown_id_asks_clarification():
    proposal = ActionProposal(
        type="fact_resolution",
        confidence=0.9,
        user_intent_summary="resolution",
        evidence=(),
        fact_resolution=FactResolutionDraft(fact_id=999, reason="passée"),
    )
    decision = RuntimePolicy().evaluate(proposal, _snapshot((_fact_view(1),)))

    assert decision.action == "ask_clarification"
    assert decision.reason == "fact_not_active"
    assert decision.commands == ()


# --- tool + proposal plumbing ---

def test_propose_fact_resolution_builds_proposal():
    ctx = ToolContext(db_path="unused", snapshot=_snapshot((_fact_view(1),)))
    proposal = propose_fact_resolution(ctx, fact_id=1, reason="douleur passée")

    assert proposal.type == "fact_resolution"
    assert proposal.fact_resolution == FactResolutionDraft(fact_id=1, reason="douleur passée")


def test_tool_catalog_registers_fact_resolution():
    event = InputEvent(
        id="evt", user_id=1, source="test", type="user_message",
        text="c'est bon", payload={}, occurred_at=NOW,
    )
    names = {tool.name for tool in tool_catalog.for_event(event, _snapshot((_fact_view(1),)))}
    assert "propose_fact_resolution" in names


def test_proposal_round_trip_fact_resolution():
    proposal = ActionProposal(
        type="fact_resolution",
        confidence=0.9,
        user_intent_summary="resolution",
        evidence=("douleur passée",),
        fact_resolution=FactResolutionDraft(fact_id=1, reason="douleur passée"),
    )
    restored = proposal_from_dict(proposal_to_dict(proposal))
    assert restored.fact_resolution == FactResolutionDraft(fact_id=1, reason="douleur passée")
