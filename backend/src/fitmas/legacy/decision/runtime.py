from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol, Sequence

from .input_event import InputEvent
from .outcome import Command, CommandResult, DecisionOutcome
from .understanding import CoachUnderstanding


@dataclass(frozen=True, slots=True)
class DecisionResult:
    event: InputEvent
    outcome: DecisionOutcome
    reply_text: str


class DecisionRuntime(Protocol):
    def run(self, event: InputEvent) -> DecisionResult:
        ...


class RuntimeContextBuilder(Protocol):
    def build(self, event: InputEvent) -> Any:
        ...


class RuntimeUnderstandingService(Protocol):
    def understand(self, event: InputEvent, context: Any) -> CoachUnderstanding:
        ...


class RuntimeDecisionEngine(Protocol):
    def decide(self, event: InputEvent, context: Any, understanding: CoachUnderstanding) -> DecisionOutcome:
        ...


class RuntimeCommandBus(Protocol):
    def apply(self, commands: Sequence[Command]) -> tuple[CommandResult, ...]:
        ...


class RuntimeReplyComposer(Protocol):
    def compose(self, outcome: DecisionOutcome, context: Any, event: InputEvent) -> str:
        ...


@dataclass(frozen=True, slots=True)
class DecisionRuntimeService:
    context_builder: RuntimeContextBuilder
    understanding_service: RuntimeUnderstandingService
    decision_engine: RuntimeDecisionEngine
    command_bus: RuntimeCommandBus
    reply_composer: RuntimeReplyComposer

    def run(self, event: InputEvent) -> DecisionResult:
        context = self.context_builder.build(event)
        understanding = self.understanding_service.understand(event, context)
        outcome = self.decision_engine.decide(event, context, understanding)
        if outcome.commands:
            applied_commands = self.command_bus.apply(outcome.commands)
            outcome = replace(outcome, applied_commands=applied_commands)
        reply_text = self.reply_composer.compose(outcome, context, event)
        return DecisionResult(event=event, outcome=outcome, reply_text=reply_text)
