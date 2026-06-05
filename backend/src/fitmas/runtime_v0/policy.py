from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import json
from typing import Any, Literal

from fitmas.runtime_v0.proposals import ActionProposal, PlanPatchDraft, PlanPatchOperation, proposal_to_dict
from fitmas.runtime_v0.snapshot import CommandEventView, SessionView, WorldSnapshot
from fitmas.runtime_v0.sport_rules import evaluate_plan_patch_sport_rules

class Command:
    pass

@dataclass(frozen=True)
class SetSessionStatusCommand(Command):
    session_id: int
    status: Literal["done", "skipped", "partial", "planned"]
    duration_min: int | None
    intensity_note: str | None
    evidence: str

@dataclass(frozen=True)
class CorrectSessionStatusCommand(Command):
    previous_event_id: int
    session_id: int
    status: Literal["done", "skipped", "partial", "planned"]
    duration_min: int | None
    intensity_note: str | None
    evidence: str

@dataclass(frozen=True)
class ApplyPlanPatchCommand(Command):
    operations: tuple[PlanPatchOperation, ...]
    rationale: str

@dataclass(frozen=True)
class CreatePendingConfirmationCommand(Command):
    type: str
    summary: str
    payload_json: str
    expires_at: datetime

@dataclass(frozen=True)
class UpsertMemoryFactCommand(Command):
    kind: str
    text: str
    confidence: float
    expires_at: datetime | None

@dataclass(frozen=True)
class ResolveMemoryFactCommand(Command):
    fact_id: int
    reason: str

@dataclass(frozen=True)
class UpdateConversationStateCommand(Command):
    last_unresolved_intent: dict | None
    last_execution_event_id: int | None
    last_pending_id: int | None

@dataclass(frozen=True)
class PolicyDecision:
    action: Literal[
        "allow_commit",
        "create_pending",
        "block",
        "ask_clarification",
        "answer_only",
        "no_send",
    ]
    reason: str
    risk_level: Literal["low", "medium", "high"]
    commands: tuple[Command, ...]
    reply_facts: tuple[str, ...]

class RuntimePolicy:
    def evaluate(self, proposal: ActionProposal, snapshot: WorldSnapshot) -> PolicyDecision:
        if proposal.type == "answer":
            return _decision("answer_only", "answer", "low", (), proposal.answer_facts)
        if proposal.type == "no_send":
            return _decision("no_send", "no_send", "low", (), ())
        if proposal.type == "ask_clarification":
            intent = _merge_unresolved_intent(
                snapshot.conversation_state.last_unresolved_intent,
                proposal.unresolved_intent,
            )
            commands: tuple[Command, ...] = (
                UpdateConversationStateCommand(
                    last_unresolved_intent=intent,
                    last_execution_event_id=snapshot.conversation_state.last_execution_event_id,
                    last_pending_id=snapshot.conversation_state.last_pending_id,
                ),
            )
            return _decision(
                "ask_clarification",
                "clarification_needed",
                "low",
                commands,
                (proposal.clarification_question,) if proposal.clarification_question else (),
            )
        if proposal.type == "memory_update":
            decision = self._memory_update(proposal)
        elif proposal.type == "fact_resolution":
            decision = self._fact_resolution(proposal, snapshot)
        elif proposal.type == "execution_update":
            decision = self._execution_update(proposal, snapshot)
        elif proposal.type == "execution_correction":
            decision = self._execution_correction(proposal, snapshot)
        elif proposal.type == "plan_patch":
            decision = self._plan_patch(proposal, snapshot)
        else:
            decision = _decision("block", "unknown_proposal_type", "high", (), ())
        if len(decision.commands) > 3:
            return _decision("block", "too_many_commands", "high", (), ())
        return decision

    def _memory_update(self, proposal: ActionProposal) -> PolicyDecision:
        commands: list[Command] = []
        for fact in proposal.memory_updates:
            if fact.kind not in {"preference", "health", "availability", "constraint"}:
                return _decision("block", "invalid_fact_kind", "low", (), ())
            if not (0 <= fact.confidence <= 1):
                return _decision("block", "invalid_fact_confidence", "low", (), ())
            if not fact.text.strip():
                return _decision("block", "empty_fact_text", "low", (), ())
            commands.append(UpsertMemoryFactCommand(fact.kind, fact.text, fact.confidence, fact.expires_at))
        return _decision("allow_commit", "memory_update", "low", tuple(commands), proposal.evidence)

    def _fact_resolution(self, proposal: ActionProposal, snapshot: WorldSnapshot) -> PolicyDecision:
        draft = proposal.fact_resolution
        if draft is None:
            return _decision("block", "missing_fact_resolution", "low", (), ())
        # Ground the LLM-supplied fact id against DB truth before retracting.
        if draft.fact_id not in {fact.id for fact in snapshot.active_facts}:
            return _decision("ask_clarification", "fact_not_active", "low", (), ("De quelle contrainte tu parles ?",))
        reply_facts = proposal.evidence or ((draft.reason,) if draft.reason else ())
        return _decision(
            "allow_commit",
            "fact_resolution",
            "low",
            (ResolveMemoryFactCommand(draft.fact_id, draft.reason),),
            reply_facts,
        )

    def _execution_update(self, proposal: ActionProposal, snapshot: WorldSnapshot) -> PolicyDecision:
        draft = proposal.execution_update
        if draft is None:
            return _decision("block", "missing_execution_update", "low", (), ())
        session = _find_session(snapshot, draft.session_id)
        if session is None:
            return _decision("ask_clarification", "session_not_found", "low", (), ())
        if session.date > snapshot.today and draft.status in {"done", "partial"}:
            return _decision("ask_clarification", "future_session_not_completable", "medium", (), ())
        event = _execution_event_for_session(snapshot, draft.session_id)
        if event is not None:
            if event.created_at < snapshot.now - timedelta(hours=48):
                return _decision("ask_clarification", "execution_event_conflict", "low", (), ("Tu veux corriger l'événement précédent ?",))
            return _decision(
                "allow_commit",
                "execution_update_compiled_to_correction",
                "medium",
                (CorrectSessionStatusCommand(event.id, draft.session_id, draft.status, draft.duration_min, draft.intensity_note, draft.evidence),),
                proposal.evidence,
            )
        return _decision(
            "allow_commit",
            "execution_update",
            "low",
            (SetSessionStatusCommand(draft.session_id, draft.status, draft.duration_min, draft.intensity_note, draft.evidence),),
            proposal.evidence,
        )

    def _execution_correction(self, proposal: ActionProposal, snapshot: WorldSnapshot) -> PolicyDecision:
        draft = proposal.execution_correction
        if draft is None:
            return _decision("block", "missing_execution_correction", "medium", (), ())
        event = _find_event(snapshot.recent_execution_events, draft.previous_event_id)
        if event is None:
            return _decision("block", "event_not_found", "medium", (), ())
        if event.created_at < snapshot.now - timedelta(hours=48):
            return _decision("block", "event_too_old", "medium", (), ())
        if event.target_session_id is not None and draft.correct_session_id != event.target_session_id:
            return _decision("ask_clarification", "correction_target_mismatch", "medium", (), ())
        if _find_session(snapshot, draft.correct_session_id) is None:
            return _decision("ask_clarification", "session_not_found", "medium", (), ())
        return _decision(
            "allow_commit",
            "execution_correction",
            "medium",
            (CorrectSessionStatusCommand(draft.previous_event_id, draft.correct_session_id, draft.correct_status, draft.duration_min, draft.intensity_note, draft.evidence),),
            proposal.evidence,
        )

    def _plan_patch(self, proposal: ActionProposal, snapshot: WorldSnapshot) -> PolicyDecision:
        draft = proposal.plan_patch
        if draft is None:
            return _decision("block", "missing_plan_patch", "medium", (), ())
        sessions = {session.id: session for session in snapshot.current_plan}
        touched: list[SessionView] = []
        active_move_target = _active_move_target(snapshot.conversation_state.last_unresolved_intent)
        for op in draft.operations:
            session = sessions.get(op.source_session_id)
            if session is None:
                return _decision("ask_clarification", "source_session_not_found", "medium", (), ())
            if op.kind == "move" and op.target_date is None:
                return _decision("ask_clarification", "target_date_missing", "medium", (), ())
            if op.kind == "move" and active_move_target is not None and op.target_date != active_move_target:
                return _decision("ask_clarification", "unresolved_intent_target_mismatch", "medium", (), ())
            if op.target_date is not None:
                if op.target_date < snapshot.today or op.target_date > snapshot.today + timedelta(days=14):
                    return _decision("ask_clarification", "target_date_out_of_range", "medium", (), ())
            touched.append(session)
        if not _plan_patch_source_anchored(proposal, active_move_target):
            return _decision(
                "ask_clarification",
                "plan_patch_source_not_anchored",
                "medium",
                (
                    UpdateConversationStateCommand(
                        _intent_from_plan_patch(draft),
                        snapshot.conversation_state.last_execution_event_id,
                        snapshot.conversation_state.last_pending_id,
                    ),
                ),
                ("Quelle séance veux-tu déplacer ?",),
            )
        compiled_draft, compile_error = _compile_plan_patch(draft, sessions)
        if compile_error is not None or compiled_draft is None:
            return _decision("block", compile_error or "invalid_plan_patch", "medium", (), proposal.evidence)
        compiled_proposal = replace(proposal, plan_patch=compiled_draft)
        command = ApplyPlanPatchCommand(operations=compiled_draft.operations, rationale=compiled_draft.rationale)
        sport_decision = evaluate_plan_patch_sport_rules(compiled_draft, snapshot)
        if sport_decision.action == "block":
            return _decision("block", sport_decision.reason, sport_decision.risk_level, (), proposal.evidence)
        if sport_decision.action == "allow":
            return _decision("allow_commit", sport_decision.reason, sport_decision.risk_level, (command,), proposal.evidence)
        pending = CreatePendingConfirmationCommand(
            type="plan_patch",
            summary=compiled_draft.rationale,
            payload_json=json.dumps(proposal_to_dict(compiled_proposal), ensure_ascii=False, sort_keys=True),
            expires_at=snapshot.now + timedelta(hours=24),
        )
        return _decision("create_pending", sport_decision.reason, sport_decision.risk_level, (pending,), proposal.evidence)

def _decision(
    action: Literal["allow_commit", "create_pending", "block", "ask_clarification", "answer_only", "no_send"],
    reason: str,
    risk_level: Literal["low", "medium", "high"],
    commands: tuple[Command, ...],
    reply_facts: tuple[str, ...],
) -> PolicyDecision:
    return PolicyDecision(action, reason, risk_level, commands, reply_facts)

def _find_session(snapshot: WorldSnapshot, session_id: int) -> SessionView | None:
    for session in (*snapshot.recent_plan, *snapshot.current_plan):
        if session.id == session_id:
            return session
    return None

def _execution_event_for_session(snapshot: WorldSnapshot, session_id: int) -> CommandEventView | None:
    for event in snapshot.recent_execution_events:
        if event.target_session_id == session_id:
            return event
    return None

def _find_event(events: tuple[CommandEventView, ...], event_id: int) -> CommandEventView | None:
    for event in events:
        if event.id == event_id:
            return event
    return None

def _merge_unresolved_intent(existing: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any] | None:
    if existing is None:
        return _normalize_unresolved_intent(incoming)
    if incoming is None:
        return _normalize_unresolved_intent(existing)
    if _intent_type(incoming) not in {None, _intent_type(existing)}:
        return _normalize_unresolved_intent(incoming)
    merged = dict(incoming)
    for key, value in existing.items():
        if key == "missing":
            continue
        if value is not None and key not in merged:
            merged[key] = value
    if "type" not in merged and "type" in existing:
        merged["type"] = existing["type"]
    return _normalize_unresolved_intent(merged)

def _normalize_unresolved_intent(intent: dict[str, Any] | None) -> dict[str, Any] | None:
    if intent is None:
        return None
    normalized = dict(intent)
    if normalized.get("type") in {"move", "plan_patch_move"}:
        normalized["type"] = "move_session"
    missing = [item for item in normalized.get("missing", ()) if isinstance(item, str) and normalized.get(item) in (None, "")]
    if missing:
        normalized["missing"] = missing
    else:
        normalized.pop("missing", None)
    return normalized

def _intent_type(intent: dict[str, Any]) -> str | None:
    value = intent.get("type")
    return value if isinstance(value, str) else None

def _active_move_target(intent: dict[str, Any] | None) -> date | None:
    if intent is None or intent.get("type") != "move_session":
        return None
    target = intent.get("target_date")
    if not isinstance(target, str):
        return None
    try:
        return date.fromisoformat(target)
    except ValueError:
        return None

def _plan_patch_source_anchored(proposal: ActionProposal, active_move_target: date | None) -> bool:
    ok_tools = {item.get("name") for item in proposal.tool_trace if item.get("ok", True)}
    return active_move_target is not None or "get_session" in ok_tools

def _intent_from_plan_patch(draft: PlanPatchDraft) -> dict[str, Any] | None:
    if len(draft.operations) != 1:
        return None
    operation = draft.operations[0]
    if operation.kind != "move" or operation.target_date is None:
        return None
    return {
        "type": "move_session",
        "target_date": operation.target_date.isoformat(),
        "missing": ["source_ref"],
    }

def _compile_plan_patch(
    draft: PlanPatchDraft,
    sessions: dict[int, SessionView],
) -> tuple[PlanPatchDraft | None, str | None]:
    operations: list[PlanPatchOperation] = []
    for operation in draft.operations:
        session = sessions.get(operation.source_session_id)
        if session is None:
            return None, "source_session_not_found"
        compiled = _compile_operation(operation, session)
        if compiled is None:
            return None, "plan_patch_has_no_effect"
        operations.append(compiled)
    return PlanPatchDraft(operations=tuple(operations), rationale=draft.rationale), None

def _compile_operation(operation: PlanPatchOperation, session: SessionView) -> PlanPatchOperation | None:
    if operation.kind == "lighten":
        intensity = operation.new_intensity_label
        duration = operation.new_duration_min
        if intensity is None and session.intensity_label != "easy":
            intensity = "easy"
        compiled = replace(operation, new_intensity_label=intensity, new_duration_min=duration)
        return compiled if _operation_has_effect(compiled, session) else None
    if _operation_has_effect(operation, session):
        return operation
    return None

def _operation_has_effect(operation: PlanPatchOperation, session: SessionView) -> bool:
    if operation.kind == "move":
        return operation.target_date is not None and operation.target_date != session.date
    if operation.kind == "swap":
        return operation.target_session_id is not None and operation.target_session_id != session.id
    if operation.kind == "lighten":
        if operation.new_intensity_label is not None and operation.new_intensity_label != session.intensity_label:
            return True
        return operation.new_duration_min is not None and operation.new_duration_min < session.duration_min
    if operation.kind == "replace":
        return any(
            (
                operation.new_sport is not None and operation.new_sport != session.sport,
                operation.new_intensity_label is not None and operation.new_intensity_label != session.intensity_label,
                operation.new_duration_min is not None and operation.new_duration_min != session.duration_min,
            )
        )
    if operation.kind == "remove_optional":
        return session.status != "skipped"
    return False
