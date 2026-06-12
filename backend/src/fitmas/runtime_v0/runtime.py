from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from time import monotonic

from fitmas.runtime_v0.agent import CoachAgent
from fitmas.runtime_v0.audit import load_turn, persist_turn
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.executor import CommandExecutor
from fitmas.runtime_v0.guard import GuardResult, OutputGuard
from fitmas.runtime_v0.idempotency import acquire_event_lock, lock_allows_retry, mark_event_lock
from fitmas.runtime_v0.llm_clients.base import LLMClient
from fitmas.runtime_v0.policy import PolicyDecision, RuntimePolicy
from fitmas.runtime_v0.prompts.coach_system import COACH_SYSTEM_PROMPT
from fitmas.runtime_v0.prompts.reply_system import REPLY_SYSTEM_PROMPT
from fitmas.runtime_v0.proposals import ActionProposal, proposal_from_dict
from fitmas.runtime_v0.reply import ReplyComposer
from fitmas.runtime_v0.result import ReplyContract, RuntimeResult, build_runtime_result
from fitmas.runtime_v0.snapshot import PendingView, SnapshotBuilder
from fitmas.runtime_v0.tool_catalog import for_event
from fitmas.runtime_v0.tools_read import ToolContext

@dataclass(frozen=True)
class RuntimeDeps:
    db_path: Path
    coach_llm: LLMClient
    reply_llm: LLMClient
    generation_llm: LLMClient | None = None
    # Coach reasoning budget (LLM round-trips). The 5x provider matrix showed 3
    # was the dominant failure cause: serial-reading models (deepseek esp.) spend
    # every round on reads and never reach the propose step -> forced no_send
    # (max_steps_reached). 6 gives headroom for ~4-5 reads + a contract retry +
    # the proposal. Raising it is monotonic-safe: passing runs already finalize
    # before the cap, so only timed-out runs change.
    max_steps: int = 6

@dataclass(frozen=True)
class HandleEventResult:
    turn_id: str
    reply: str
    proposal: ActionProposal
    policy: PolicyDecision
    runtime_result: RuntimeResult
    guard: GuardResult

def handle_event(event: InputEvent, deps: RuntimeDeps, turn_id: str) -> HandleEventResult:
    started = monotonic()
    lock = acquire_event_lock(deps.db_path, event.id, turn_id)
    turn_id = lock.turn_id
    if lock.existing and (turn := load_turn(deps.db_path, turn_id)) is not None and _turn_complete(turn):
        return _existing_result(turn)
    if lock.existing:
        if lock_allows_retry(lock):
            mark_event_lock(deps.db_path, event.id, "running")
            try:
                return _handle_new_event(event, deps, turn_id, started)
            except Exception:
                mark_event_lock(deps.db_path, event.id, "failed")
                raise
        return _processing_result(event, turn_id)
    try:
        return _handle_new_event(event, deps, turn_id, started)
    except Exception:
        mark_event_lock(deps.db_path, event.id, "failed")
        raise

def _handle_new_event(event: InputEvent, deps: RuntimeDeps, turn_id: str, started: float) -> HandleEventResult:
    snapshot = SnapshotBuilder(deps.db_path).build(event.user_id, event.occurred_at, current_event_id=event.id)
    ctx = ToolContext(deps.db_path, snapshot, {}, generation_llm=deps.generation_llm)
    if event.type != "user_message":
        proposal = _no_send("event_type_not_supported_in_v0")
        policy = RuntimePolicy().evaluate(proposal, snapshot)
        result = build_runtime_result(event, turn_id, proposal, policy, ())
        guard = GuardResult(True, (), "")
        _persist(deps, turn_id, event, snapshot, proposal, policy, result, "", guard, ctx, latency_ms=_latency_ms(started))
        mark_event_lock(deps.db_path, event.id, "completed")
        return HandleEventResult(turn_id, "", proposal, policy, result, guard)

    proposal = CoachAgent(deps.coach_llm, COACH_SYSTEM_PROMPT).run(
        event,
        snapshot.header(),
        for_event(event, snapshot),
        max_steps=deps.max_steps,
        tool_context=ctx,
    )
    policy = RuntimePolicy().evaluate(proposal, snapshot)
    events = CommandExecutor(deps.db_path).execute(policy.commands, turn_id, user_id=event.user_id)
    result = build_runtime_result(event, turn_id, proposal, policy, events, pending=_pending_from_events(events))
    reply_calls = _calls(deps.reply_llm)
    reply = ReplyComposer(deps.reply_llm, REPLY_SYSTEM_PROMPT).compose(result, snapshot)
    guarder = OutputGuard(snapshot.today)
    guard = guarder.verify(reply, result)
    guard_repair_used = False
    if not guard.ok:
        guard_repair_used = True
        retry_prompt = f"{REPLY_SYSTEM_PROMPT}\nRépare la réponse. Erreurs: {','.join(guard.blocked_reasons)}. Réponse rejetée: {reply}"
        retry = ReplyComposer(deps.reply_llm, retry_prompt).compose(result, snapshot)
        retry_guard = guarder.verify(retry, result)
        if retry_guard.ok: reply, guard = retry, retry_guard
    final_reply = reply if guard.ok else guard.sanitized_reply
    _persist(deps, turn_id, event, snapshot, proposal, policy, result, final_reply, guard, ctx, _calls(deps.reply_llm) - reply_calls, guard_repair_used, _latency_ms(started))
    mark_event_lock(deps.db_path, event.id, "completed")
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
    reply_attempts: int = 0,
    guard_repair_used: bool = False,
    latency_ms: int = 0,
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
        _provider(deps.coach_llm),
        _model(deps.coach_llm),
        latency_ms,
        _tokens(deps, "tokens_in"),
        _tokens(deps, "tokens_out"),
        reply_attempts,
        guard_repair_used,
    )

def _no_send(reason: str) -> ActionProposal:
    return ActionProposal(type="no_send", confidence=0.0, user_intent_summary=reason, evidence=(reason,))

def _processing_result(event: InputEvent, turn_id: str) -> HandleEventResult:
    proposal = _no_send("processing")
    policy = PolicyDecision("no_send", "processing", "low", (), ())
    result = build_runtime_result(event, turn_id, proposal, policy, ())
    guard = GuardResult(True, (), "")
    return HandleEventResult(turn_id, "", proposal, policy, result, guard)

def _pending_from_events(events) -> PendingView | None:
    for event in events:
        if event.command_type == "CreatePendingConfirmationCommand" and event.status == "applied":
            row = event.after
            return PendingView(row["id"], row["type"], row["summary"], datetime.fromisoformat(row["expires_at"]))
    return None

def _existing_result(turn) -> HandleEventResult:
    proposal = proposal_from_dict(json.loads(turn["proposal_json"]))
    policy_data = json.loads(turn["policy_json"])
    result_data = json.loads(turn["result_json"])
    policy = PolicyDecision(policy_data["action"], policy_data["reason"], policy_data["risk_level"], (), tuple(policy_data.get("reply_facts", ())))
    result = RuntimeResult(
        result_data["event_id"], result_data["turn_id"], result_data["proposal_type"], result_data["policy_action"],
        (), tuple(result_data.get("blocked_reasons", ())), None, tuple(result_data.get("read_facts", ())),
        ReplyContract((), (), "informative", 3),
    )
    guard = GuardResult(bool(turn["guard_ok"]), tuple(json.loads(turn["guard_reasons_json"])), turn["reply"])
    return HandleEventResult(result.turn_id, turn["reply"], proposal, policy, result, guard)

def _turn_complete(turn) -> bool:
    return bool(turn["proposal_json"] and '"type"' in turn["proposal_json"] and turn["result_json"])

def _calls(client: LLMClient) -> int:
    return int(getattr(client, "calls", len(getattr(client, "requests", ()))) or 0)

def _provider(client: LLMClient) -> str:
    return str(getattr(client, "provider", "fake") or "fake")

def _model(client: LLMClient) -> str:
    return str(getattr(client, "model", "fake") or "fake")

def _tokens(deps: RuntimeDeps, name: str) -> int:
    return int(getattr(deps.coach_llm, name, 0) or 0) + int(getattr(deps.reply_llm, name, 0) or 0)

def _latency_ms(started: float) -> int:
    return max(1, int((monotonic() - started) * 1000))
