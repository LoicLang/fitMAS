from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fitmas.runtime_v0.agent import CoachAgent
from fitmas.runtime_v0.audit import persist_turn
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.executor import CommandExecutor
from fitmas.runtime_v0.guard import GuardResult, OutputGuard
from fitmas.runtime_v0.llm_clients.base import LLMClient
from fitmas.runtime_v0.policy import PolicyDecision, RuntimePolicy
from fitmas.runtime_v0.prompts.coach_system import COACH_SYSTEM_PROMPT
from fitmas.runtime_v0.prompts.reply_system import REPLY_SYSTEM_PROMPT
from fitmas.runtime_v0.proposals import ActionProposal
from fitmas.runtime_v0.reply import ReplyComposer
from fitmas.runtime_v0.result import RuntimeResult, build_runtime_result
from fitmas.runtime_v0.snapshot import SnapshotBuilder
from fitmas.runtime_v0.tool_catalog import for_event
from fitmas.runtime_v0.tools_read import ToolContext


@dataclass(frozen=True)
class RuntimeDeps:
    db_path: Path
    coach_llm: LLMClient
    reply_llm: LLMClient


@dataclass(frozen=True)
class HandleEventResult:
    turn_id: str
    reply: str
    proposal: ActionProposal
    policy: PolicyDecision
    runtime_result: RuntimeResult
    guard: GuardResult


def handle_event(event: InputEvent, deps: RuntimeDeps, turn_id: str) -> HandleEventResult:
    snapshot = SnapshotBuilder(deps.db_path).build(event.user_id, event.occurred_at)
    ctx = ToolContext(deps.db_path, snapshot, {})
    if event.type != "user_message":
        proposal = _no_send("event_type_not_supported_in_v0")
        policy = RuntimePolicy().evaluate(proposal, snapshot)
        result = build_runtime_result(event, turn_id, proposal, policy, ())
        guard = GuardResult(True, (), "")
        _persist(deps, turn_id, event, snapshot, proposal, policy, result, "", guard, ctx)
        return HandleEventResult(turn_id, "", proposal, policy, result, guard)

    proposal = CoachAgent(deps.coach_llm, COACH_SYSTEM_PROMPT).run(
        event,
        snapshot.header(),
        for_event(event, snapshot),
        tool_context=ctx,
    )
    policy = RuntimePolicy().evaluate(proposal, snapshot)
    events = CommandExecutor(deps.db_path).execute(policy.commands, turn_id)
    result = build_runtime_result(event, turn_id, proposal, policy, events)
    reply = ReplyComposer(deps.reply_llm, REPLY_SYSTEM_PROMPT).compose(result, snapshot)
    guarder = OutputGuard(snapshot.today)
    guard = guarder.verify(reply, result)
    if not guard.ok:
        retry_prompt = f"{REPLY_SYSTEM_PROMPT}\nRépare la réponse. Erreurs: {','.join(guard.blocked_reasons)}. Réponse rejetée: {reply}"
        retry = ReplyComposer(deps.reply_llm, retry_prompt).compose(result, snapshot)
        retry_guard = guarder.verify(retry, result)
        if retry_guard.ok: reply, guard = retry, retry_guard
    final_reply = reply if guard.ok else guard.sanitized_reply
    _persist(deps, turn_id, event, snapshot, proposal, policy, result, final_reply, guard, ctx)
    return HandleEventResult(turn_id, final_reply, proposal, policy, result, guard)


def _persist(
    deps: RuntimeDeps,
    turn_id: str,
    event: InputEvent,
    snapshot,
    proposal: ActionProposal,
    policy: PolicyDecision,
    result: RuntimeResult,
    reply: str,
    guard: GuardResult,
    ctx: ToolContext,
) -> None:
    persist_turn(
        deps.db_path,
        turn_id,
        event,
        snapshot,
        proposal,
        policy,
        result,
        reply,
        guard,
        list(ctx.scratchpad.get("calls", [])),
        "llm",
    )


def _no_send(reason: str) -> ActionProposal:
    return ActionProposal(type="no_send", confidence=0.0, user_intent_summary=reason, evidence=(reason,))
