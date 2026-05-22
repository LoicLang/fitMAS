from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fitmas.decision import (
    CoachUnderstanding,
    Command,
    CommandResult,
    DecisionExplanation,
    DecisionOutcome,
    InputEvent,
    ReplyContract,
)
from fitmas.decision.runtime import DecisionRuntimeService


def _event() -> InputEvent:
    return InputEvent(
        id="evt_1",
        user_id=1,
        source="telegram",
        type="user_message",
        text="deplace demain",
        payload={},
        occurred_at=datetime(2026, 5, 14, 8, 0, tzinfo=UTC),
    )


def _understanding() -> CoachUnderstanding:
    return CoachUnderstanding(
        intent="plan_lookup",
        confidence=0.9,
        user_summary="lookup",
        extracted_signals=(),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )


def _outcome() -> DecisionOutcome:
    return DecisionOutcome(
        kind="answer",
        commands=(
            Command(
                id="cmd_1",
                domain="memory",
                name="record_note",
                payload={"summary": "note"},
            ),
        ),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Reponse",
            reason_summary="Plan lu.",
            evidence=("runtime_service",),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="answer",
            audience="conversation",
            allowed_claims=("answer",),
            forbidden_claims=("plan_committed_without_event",),
        ),
    )


@dataclass
class SpyContextBuilder:
    calls: list[str]

    def build(self, event):
        self.calls.append(f"context:{event.id}")
        return {"context": True}


@dataclass
class SpyUnderstandingService:
    calls: list[str]

    def understand(self, event, context):
        self.calls.append(f"understand:{event.id}:{bool(context)}")
        return _understanding()


@dataclass
class SpyDecisionEngine:
    calls: list[str]

    def decide(self, event, context, understanding):
        self.calls.append(f"decide:{event.id}:{understanding.intent}")
        return _outcome()


@dataclass
class SpyCommandBus:
    calls: list[str]

    def apply(self, commands):
        self.calls.append(f"commands:{len(commands)}")
        return (
            CommandResult(
                command_id="cmd_1",
                domain="memory",
                name="record_note",
                status="applied",
                event_id="mem_evt_1",
                payload={"summary": "note saved"},
            ),
        )


@dataclass
class SpyReplyComposer:
    calls: list[str]

    def compose(self, outcome, context, event):
        self.calls.append(f"reply:{outcome.kind}:{len(outcome.applied_commands)}")
        return "Plan lu."


def test_runtime_service_runs_context_understanding_decision_commands_reply_in_order() -> None:
    calls: list[str] = []
    service = DecisionRuntimeService(
        context_builder=SpyContextBuilder(calls),
        understanding_service=SpyUnderstandingService(calls),
        decision_engine=SpyDecisionEngine(calls),
        command_bus=SpyCommandBus(calls),
        reply_composer=SpyReplyComposer(calls),
    )

    result = service.run(_event())

    assert result.reply_text == "Plan lu."
    assert result.outcome.applied_commands[0].event_id == "mem_evt_1"
    assert calls == [
        "context:evt_1",
        "understand:evt_1:True",
        "decide:evt_1:plan_lookup",
        "commands:1",
        "reply:answer:1",
    ]


def test_runtime_service_skips_command_bus_when_outcome_has_no_commands() -> None:
    calls: list[str] = []

    class NoCommandEngine(SpyDecisionEngine):
        def decide(self, event, context, understanding):
            outcome = _outcome()
            return DecisionOutcome(
                kind=outcome.kind,
                commands=(),
                applied_commands=(),
                candidates=outcome.candidates,
                selected_candidate_id=outcome.selected_candidate_id,
                explanation=outcome.explanation,
                reply_contract=outcome.reply_contract,
            )

    service = DecisionRuntimeService(
        context_builder=SpyContextBuilder(calls),
        understanding_service=SpyUnderstandingService(calls),
        decision_engine=NoCommandEngine(calls),
        command_bus=SpyCommandBus(calls),
        reply_composer=SpyReplyComposer(calls),
    )

    result = service.run(_event())

    assert result.reply_text == "Plan lu."
    assert "commands:0" not in calls
