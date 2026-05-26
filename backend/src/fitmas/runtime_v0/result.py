from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.executor import CommandEvent
from fitmas.runtime_v0.policy import PolicyDecision
from fitmas.runtime_v0.proposals import ActionProposal
from fitmas.runtime_v0.snapshot import PendingView

@dataclass(frozen=True)
class ReplyContract:
    must_include: tuple[str, ...]
    must_not_claim: tuple[str, ...]
    tone: Literal["informative", "confirming", "asking", "explaining_block"]
    max_sentences: int

@dataclass(frozen=True)
class RuntimeResult:
    event_id: str
    turn_id: str
    proposal_type: str
    policy_action: str
    committed_events: tuple[CommandEvent, ...]
    blocked_reasons: tuple[str, ...]
    pending: PendingView | None
    read_facts: tuple[str, ...]
    reply_contract: ReplyContract

def build_runtime_result(
    event: InputEvent,
    turn_id: str,
    proposal: ActionProposal,
    policy: PolicyDecision,
    command_events: tuple[CommandEvent, ...],
    pending: PendingView | None = None,
    blocked_reasons: tuple[str, ...] = (),
) -> RuntimeResult:
    policy_blocks = (policy.reason,) if policy.action == "block" else ()
    blocked = blocked_reasons + policy_blocks + tuple(
        event.reason for event in command_events if event.status == "blocked"
    )
    read_facts = policy.reply_facts or proposal.answer_facts
    return RuntimeResult(
        event_id=event.id,
        turn_id=turn_id,
        proposal_type=proposal.type,
        policy_action=policy.action,
        committed_events=tuple(event for event in command_events if event.status == "applied"),
        blocked_reasons=blocked,
        pending=pending,
        read_facts=read_facts,
        reply_contract=ReplyContract(
            must_include=_must_include(policy, pending),
            must_not_claim=_must_not_claim(command_events, pending),
            tone=_tone(policy.action, bool(blocked), pending),
            max_sentences=3,
        ),
    )

def _must_include(policy: PolicyDecision, pending: PendingView | None) -> tuple[str, ...]:
    values = list(policy.reply_facts)
    if pending is not None:
        values.append(pending.summary)
    return tuple(values)

def _must_not_claim(command_events: tuple[CommandEvent, ...], pending: PendingView | None) -> tuple[str, ...]:
    if pending is not None:
        return ("c'est fait", "appliqué")
    if not any(event.status == "applied" for event in command_events):
        return ("j'ai déplacé", "j'ai modifié", "c'est fait")
    return ()

def _tone(policy_action: str, blocked: bool, pending: PendingView | None) -> Literal[
    "informative", "confirming", "asking", "explaining_block"
]:
    if blocked:
        return "explaining_block"
    if pending is not None or policy_action in {"ask_clarification", "create_pending"}:
        return "asking"
    if policy_action == "allow_commit":
        return "confirming"
    return "informative"
