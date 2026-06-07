from __future__ import annotations

from datetime import datetime, timezone

from fitmas.runtime_v0.agent import CoachAgent
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.meso.runtime_tool import propose_week
from fitmas.runtime_v0.policy import RuntimePolicy
from fitmas.runtime_v0.tool_catalog import for_event
from fitmas.runtime_v0.proposals import (
    ActionProposal,
    WeekProposalDraft,
    proposal_from_dict,
    proposal_to_dict,
)
from fitmas.runtime_v0.snapshot import WorldSnapshot
from fitmas.runtime_v0.state import ConversationState
from fitmas.runtime_v0.tools_read import ToolContext


def _draft() -> WeekProposalDraft:
    return WeekProposalDraft(
        week_start="2026-06-08",
        source="llm",
        week_load=315.0,
        band=(300.0, 330.0),
        key_type="threshold",
        sessions=(
            {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard", "detail": "3x8"},
            {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate", "detail": ""},
        ),
    )


def test_week_proposal_roundtrips():
    proposal = ActionProposal(
        type="week_proposal",
        confidence=0.8,
        user_intent_summary="week proposal",
        evidence=("semaine proposée",),
        answer_facts=("semaine proposée",),
        week_proposal=_draft(),
    )
    restored = proposal_from_dict(proposal_to_dict(proposal))
    assert restored.type == "week_proposal"
    assert restored.week_proposal == _draft()
    assert restored.week_proposal.band == (300.0, 330.0)
    assert restored.week_proposal.sessions[0]["type"] == "threshold"


NOW = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)  # a Thursday

_GOOD_WEEK = [
    {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard"},   # 100
    {"date": "2026-06-11", "type": "easy_run", "duration_min": 60, "intensity": "easy"},     # 60
    {"date": "2026-06-13", "type": "easy_run", "duration_min": 50, "intensity": "easy"},     # 50
    {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate"}, # 105
]


def _snapshot(facts=()):
    return WorldSnapshot(
        user_id=1, today=NOW.date(), now=NOW, timezone="UTC", objective=None,
        current_plan=(), recent_plan=(), recent_activities=(), active_facts=facts,
        active_pending=None, recent_execution_events=(), recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )


def _emit(sessions):
    return LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": sessions}),))


def test_propose_week_generates_and_returns_week_proposal():
    generation_llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    ctx = ToolContext(db_path=None, snapshot=_snapshot(), generation_llm=generation_llm)
    proposal = propose_week(ctx, last_week_load=300.0, key_type="threshold")
    assert proposal.type == "week_proposal"
    assert proposal.week_proposal.source == "llm"
    assert proposal.week_proposal.band == (300.0, 330.0)  # build 100->110% of 300
    assert proposal.week_proposal.week_start == "2026-06-08"  # next Monday after Thu 06-04
    assert len(proposal.week_proposal.sessions) == 4
    assert proposal.answer_facts  # week summary lines for the reply


def test_policy_shows_week_proposal_without_commit():
    generation_llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    ctx = ToolContext(db_path=None, snapshot=_snapshot(), generation_llm=generation_llm)
    proposal = propose_week(ctx, last_week_load=300.0, key_type="threshold")
    decision = RuntimePolicy().evaluate(proposal, _snapshot())
    assert decision.action == "answer_only"
    assert decision.commands == ()  # 3a never writes
    assert decision.reply_facts == proposal.answer_facts


def test_propose_week_registered_for_user_message():
    event = InputEvent(
        id="e1",
        user_id=1,
        source="test",
        type="user_message",
        text="fais-moi ma semaine",
        payload={},
        occurred_at=NOW,
    )
    tools = {tool.name: tool for tool in for_event(event, _snapshot())}
    assert "propose_week" in tools
    schema = tools["propose_week"]
    assert schema.is_proposal is True
    assert "last_week_load" in schema.parameters["properties"]
    assert "key_type" in schema.parameters["properties"]


def test_coach_calls_propose_week_end_to_end():
    # Coach LLM asks for a week; generation LLM emits the typed week.
    coach_llm = FakeLLMClient([
        LLMResponse(tool_calls=(ToolCall(name="propose_week", args={"last_week_load": 300.0, "key_type": "threshold"}),)),
    ])
    generation_llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    snapshot = _snapshot()
    ctx = ToolContext(db_path=None, snapshot=snapshot, generation_llm=generation_llm)
    event = InputEvent(id="e1", user_id=1, source="test", type="user_message", text="fais-moi ma semaine", payload={}, occurred_at=NOW)
    proposal = CoachAgent(coach_llm, "sys").run(
        event, snapshot.header(), for_event(event, snapshot), max_steps=3, tool_context=ctx
    )
    assert proposal.type == "week_proposal"
    assert proposal.week_proposal.source == "llm"
    # the generation client was used, not the coach client
    assert len(generation_llm.requests) == 1
