from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fitmas.runtime_v0.proposals import (
    ActionProposal,
    ExecutionCorrectionDraft,
    ExecutionUpdateDraft,
    FactResolutionDraft,
    MemoryFactDraft,
    PlanPatchDraft,
    PlanPatchOperation,
)
from fitmas.runtime_v0.tools_read import ToolContext

def propose_execution_update(
    ctx: ToolContext,
    session_id: int,
    status: str,
    duration_min: int | None = None,
    intensity_note: str | None = None,
    evidence: str = "",
) -> ActionProposal:
    _record(ctx, "propose_execution_update", True)
    return ActionProposal(
        type="execution_update",
        confidence=0.8,
        user_intent_summary="execution update",
        evidence=(evidence,) if evidence else (),
        tool_trace=_trace(ctx),
        execution_update=ExecutionUpdateDraft(
            session_id=session_id,
            status=status,
            duration_min=duration_min,
            intensity_note=intensity_note,
            evidence=evidence,
        ),
    )

def propose_execution_correction(
    ctx: ToolContext,
    previous_event_id: int,
    correct_session_id: int,
    correct_status: str,
    duration_min: int | None = None,
    intensity_note: str | None = None,
    evidence: str = "",
) -> ActionProposal:
    _record(ctx, "propose_execution_correction", True)
    return ActionProposal(
        type="execution_correction",
        confidence=0.8,
        user_intent_summary="execution correction",
        evidence=(evidence,) if evidence else (),
        tool_trace=_trace(ctx),
        execution_correction=ExecutionCorrectionDraft(
            previous_event_id=previous_event_id,
            correct_session_id=correct_session_id,
            correct_status=correct_status,
            duration_min=duration_min,
            intensity_note=intensity_note,
            evidence=evidence,
        ),
    )

def propose_plan_patch(
    ctx: ToolContext,
    operations: list[dict[str, Any]],
    rationale: str,
) -> ActionProposal:
    _record(ctx, "propose_plan_patch", True)
    return ActionProposal(
        type="plan_patch",
        confidence=0.75,
        user_intent_summary="plan patch",
        evidence=(rationale,) if rationale else (),
        tool_trace=_trace(ctx),
        plan_patch=PlanPatchDraft(
            operations=tuple(_operation_from_dict(item) for item in operations),
            rationale=rationale,
        ),
    )

def propose_memory_update(
    ctx: ToolContext,
    kind: str,
    text: str,
    confidence: float,
    expires_at: str | None = None,
) -> ActionProposal:
    _record(ctx, "propose_memory_update", True)
    return ActionProposal(
        type="memory_update",
        confidence=confidence,
        user_intent_summary="memory update",
        evidence=(text,),
        tool_trace=_trace(ctx),
        memory_updates=(
            MemoryFactDraft(
                kind=kind,
                text=text,
                confidence=confidence,
                expires_at=_parse_optional_datetime(expires_at),
            ),
        ),
    )

def propose_fact_resolution(
    ctx: ToolContext,
    fact_id: int,
    reason: str = "",
) -> ActionProposal:
    _record(ctx, "propose_fact_resolution", True)
    return ActionProposal(
        type="fact_resolution",
        confidence=0.9,
        user_intent_summary="fact resolution",
        evidence=(reason,) if reason else (),
        tool_trace=_trace(ctx),
        fact_resolution=FactResolutionDraft(fact_id=fact_id, reason=reason),
    )

def ask_clarification(
    ctx: ToolContext,
    question: str,
    unresolved_intent: dict[str, Any] | None = None,
) -> ActionProposal:
    _record(ctx, "ask_clarification", True)
    return ActionProposal(
        type="ask_clarification",
        confidence=1.0,
        user_intent_summary="clarification needed",
        evidence=(),
        clarification_question=question,
        unresolved_intent=unresolved_intent,
        tool_trace=_trace(ctx),
    )

def _operation_from_dict(data: dict[str, Any]) -> PlanPatchOperation:
    kind = data["kind"]
    return PlanPatchOperation(
        kind=kind,
        source_session_id=data["source_session_id"],
        target_date=_parse_optional_date(data.get("target_date")) if kind == "move" else None,
        target_session_id=data.get("target_session_id"),
        new_intensity_label=_normalize_intensity(data.get("new_intensity_label")),
        new_sport=_normalize_sport(data.get("new_sport")),
        new_duration_min=data.get("new_duration_min"),
    )

def _parse_optional_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)

def _parse_optional_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)

def _normalize_intensity(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    aliases = {
        "facile": "easy",
        "easy": "easy",
        "modéré": "moderate",
        "moderee": "moderate",
        "modérée": "moderate",
        "moderate": "moderate",
        "dur": "hard",
        "dure": "hard",
        "hard": "hard",
    }
    return aliases.get(normalized, normalized)

def _normalize_sport(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    aliases = {
        "vélo": "bike",
        "velo": "bike",
        "bike": "bike",
        "cycling": "bike",
        "cyclisme": "bike",
        "course": "run",
        "running": "run",
        "run": "run",
        "natation": "swim",
        "swimming": "swim",
        "swim": "swim",
        "renfo": "strength",
        "strength": "strength",
        "mobilité": "mobility",
        "mobility": "mobility",
        "repos": "rest",
        "rest": "rest",
    }
    return aliases.get(normalized, normalized)

def _record(ctx: ToolContext, name: str, ok: bool) -> None:
    calls = ctx.scratchpad.setdefault("calls", [])
    calls.append({"name": name, "ok": ok})

def _trace(ctx: ToolContext) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in ctx.scratchpad.get("calls", ()))
