from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.executor import CommandEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.policy import PolicyDecision
from fitmas.runtime_v0.proposals import ActionProposal
from fitmas.runtime_v0.reply import ReplyComposer
from fitmas.runtime_v0.result import build_runtime_result
from fitmas.runtime_v0.snapshot import PendingView, SnapshotBuilder
from fitmas.runtime_v0.db import init_db


PARIS = ZoneInfo("Europe/Paris")


def _event() -> InputEvent:
    return InputEvent(
        id="evt-1",
        user_id=1,
        source="test",
        type="user_message",
        text="Plan actuel ?",
        payload={},
        occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=PARIS),
    )


def _snapshot(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    return SnapshotBuilder(db_path).build(1, _event().occurred_at)


def _applied_event() -> CommandEvent:
    return CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="SetSessionStatusCommand",
        target_type="session",
        target_id="60",
        status="applied",
        before={"status": "planned"},
        after={"status": "skipped"},
        reason="user skipped",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )


def test_build_runtime_result_carries_commits_blocks_pending_and_contract():
    event = _event()
    proposal = ActionProposal(
        type="execution_update",
        confidence=0.8,
        user_intent_summary="skipped",
        evidence=("user skipped",),
    )
    pending = PendingView(
        id=2,
        type="plan_patch",
        summary="move key session",
        expires_at=datetime(2026, 5, 23, 14, 0, tzinfo=PARIS),
    )
    policy = PolicyDecision(
        action="create_pending",
        reason="needs confirmation",
        risk_level="medium",
        commands=(),
        reply_facts=("confirmation needed",),
    )

    result = build_runtime_result(
        event=event,
        turn_id="turn-1",
        proposal=proposal,
        policy=policy,
        command_events=(_applied_event(),),
        pending=pending,
        blocked_reasons=("blocked detail",),
    )

    assert result.event_id == "evt-1"
    assert result.proposal_type == "execution_update"
    assert result.policy_action == "create_pending"
    assert result.committed_events[0].target_id == "60"
    assert result.pending is pending
    assert "confirmation needed" in result.reply_contract.must_include
    assert "blocked detail" in result.blocked_reasons
    assert result.reply_contract.tone == "explaining_block"

    pending_only = build_runtime_result(
        event=event,
        turn_id="turn-2",
        proposal=proposal,
        policy=policy,
        command_events=(),
        pending=pending,
    )
    assert pending_only.reply_contract.tone == "asking"


def test_reply_composer_uses_llm_response_and_fallbacks(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    proposal = ActionProposal(
        type="answer",
        confidence=0.8,
        user_intent_summary="answer",
        evidence=("2026-05-22 Footing",),
        answer_facts=("2026-05-22 Footing",),
    )
    policy = PolicyDecision(
        action="answer_only",
        reason="answer",
        risk_level="low",
        commands=(),
        reply_facts=("2026-05-22 Footing",),
    )
    result = build_runtime_result(event, "turn-1", proposal, policy, ())
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text="Aujourd'hui: Footing.")]), "reply-system")

    assert composer.compose(result, snapshot) == "Aujourd'hui: Footing."

    failing = ReplyComposer(FakeLLMClient([]), "reply-system")
    assert failing.compose(result, snapshot) == "2026-05-22 Footing"

    non_answer = build_runtime_result(
        event,
        "turn-2",
        ActionProposal(type="no_send", confidence=0.0, user_intent_summary="none", evidence=()),
        PolicyDecision(action="no_send", reason="none", risk_level="low", commands=(), reply_facts=()),
        (),
    )
    assert failing.compose(non_answer, snapshot) == "Je n'ai pas pu traiter ça proprement. Réessaie dans un instant."


def test_reply_composer_retries_plan_answer_that_omits_read_sessions(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    read_fact = (
        '{"sessions": ['
        '{"date": "2026-05-22", "title": "Footing recup"},'
        '{"date": "2026-05-24", "title": "VMA courte"},'
        '{"date": "2026-05-26", "title": "Endurance"}'
        ']}'
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="answer", confidence=0.8, user_intent_summary="answer", evidence=(read_fact,), answer_facts=(read_fact,)),
        PolicyDecision(action="answer_only", reason="answer", risk_level="low", commands=(), reply_facts=(read_fact,)),
        (),
    )
    client = FakeLLMClient(
        [
            LLMResponse(text="Aujourd'hui footing."),
            LLMResponse(text="22 Footing recup. 24 VMA courte. 26 Endurance."),
        ]
    )
    composer = ReplyComposer(client, "reply-system")

    reply = composer.compose(result, snapshot)

    assert reply == "22 Footing recup. 24 VMA courte. 26 Endurance."
    assert "Réponse rejetée" in client.requests[1]["system"]


def test_reply_composer_returns_clarification_question_without_llm(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="ask_clarification", confidence=1.0, user_intent_summary="clarify", evidence=()),
        PolicyDecision(
            action="ask_clarification",
            reason="clarify",
            risk_level="low",
            commands=(),
            reply_facts=("Quelle séance ?",),
        ),
        (),
    )

    assert ReplyComposer(FakeLLMClient([]), "reply-system").compose(result, snapshot) == "Quelle séance ?"


def test_reply_composer_pending_fallback_asks_confirmation(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    pending = PendingView(
        id=2,
        type="plan_patch",
        summary="déplacer la VMA à vendredi",
        expires_at=datetime(2026, 5, 23, 14, 0, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="move", evidence=("x",)),
        PolicyDecision(action="create_pending", reason="needs confirmation", risk_level="medium", commands=(), reply_facts=()),
        (),
        pending=pending,
    )

    reply = ReplyComposer(FakeLLMClient([]), "reply-system").compose(result, snapshot)

    assert reply == "Je dois confirmer avant de faire ça: déplacer la VMA à vendredi."


def test_reply_composer_pending_uses_deterministic_confirmation(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    pending = PendingView(
        id=2,
        type="plan_patch",
        summary="déplacer la VMA à vendredi",
        expires_at=datetime(2026, 5, 23, 14, 0, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="move", evidence=("x",)),
        PolicyDecision(action="create_pending", reason="needs confirmation", risk_level="medium", commands=(), reply_facts=()),
        (),
        pending=pending,
    )
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text="Je n'ai pas pu traiter ça proprement.")]), "reply-system")

    reply = composer.compose(result, snapshot)

    assert reply == "Je dois confirmer avant de faire ça: déplacer la VMA à vendredi."


def test_reply_composer_uses_committed_execution_summary(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    command = _applied_event()
    command = CommandEvent(
        id=command.id,
        turn_id=command.turn_id,
        command_type=command.command_type,
        target_type=command.target_type,
        target_id=command.target_id,
        status=command.status,
        before=command.before,
        after={"date": "2026-05-21", "status": "skipped"},
        reason=command.reason,
        created_at=command.created_at,
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="execution_update", confidence=0.8, user_intent_summary="skipped", evidence=("x",)),
        PolicyDecision(action="allow_commit", reason="x", risk_level="low", commands=(), reply_facts=("x",)),
        (command,),
    )
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text="J’enregistre la séance du 21 mai.")]), "reply-system")

    assert composer.compose(result, snapshot) == "Noté pour hier."


def test_reply_composer_uses_committed_plan_patch_summary(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    command = CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="ApplyPlanPatchCommand",
        target_type="session",
        target_id="60",
        status="applied",
        before={},
        after={"60": {"date": "2026-05-29"}},
        reason="move",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="move", evidence=("x",)),
        PolicyDecision(action="allow_commit", reason="x", risk_level="low", commands=(), reply_facts=("x",)),
        (command,),
    )
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text="Déplacement au 29 mai.")]), "reply-system")

    assert composer.compose(result, snapshot) == "Déplacé à vendredi."
