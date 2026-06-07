from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from typing import Any, Literal

@dataclass(frozen=True)
class MemoryFactDraft:
    kind: Literal["preference", "health", "availability", "constraint"]
    text: str
    confidence: float
    expires_at: datetime | None

@dataclass(frozen=True)
class ExecutionUpdateDraft:
    session_id: int
    status: Literal["done", "skipped", "partial"]
    duration_min: int | None = None
    intensity_note: str | None = None
    evidence: str = ""

@dataclass(frozen=True)
class ExecutionCorrectionDraft:
    previous_event_id: int
    correct_session_id: int
    correct_status: Literal["done", "skipped", "partial", "planned"]
    duration_min: int | None = None
    intensity_note: str | None = None
    evidence: str = ""

@dataclass(frozen=True)
class PlanPatchOperation:
    kind: Literal["move", "swap", "lighten", "replace", "remove_optional"]
    source_session_id: int
    target_date: date | None = None
    target_session_id: int | None = None
    new_intensity_label: str | None = None
    new_sport: str | None = None
    new_duration_min: int | None = None

@dataclass(frozen=True)
class PlanPatchDraft:
    operations: tuple[PlanPatchOperation, ...]
    rationale: str

@dataclass(frozen=True)
class FactResolutionDraft:
    fact_id: int
    reason: str = ""

@dataclass(frozen=True)
class WeekProposalDraft:
    week_start: str  # ISO date of the Monday the week anchors on
    source: str  # "llm" | "template_fallback"
    week_load: float
    band: tuple[float, float]
    key_type: str
    sessions: tuple[dict[str, Any], ...]  # {date, type, duration_min, intensity, detail}

@dataclass(frozen=True)
class PendingResolutionDraft:
    pending_id: int
    decision: Literal["accept", "reject"]
    note: str = ""

@dataclass(frozen=True)
class ActionProposal:
    type: Literal[
        "answer",
        "ask_clarification",
        "memory_update",
        "execution_update",
        "execution_correction",
        "plan_patch",
        "fact_resolution",
        "week_proposal",
        "pending_resolution",
        "no_send",
    ]
    confidence: float
    user_intent_summary: str
    evidence: tuple[str, ...]
    answer_facts: tuple[str, ...] = ()
    clarification_question: str | None = None
    memory_updates: tuple[MemoryFactDraft, ...] = ()
    execution_update: ExecutionUpdateDraft | None = None
    execution_correction: ExecutionCorrectionDraft | None = None
    plan_patch: PlanPatchDraft | None = None
    fact_resolution: FactResolutionDraft | None = None
    week_proposal: WeekProposalDraft | None = None
    pending_resolution: PendingResolutionDraft | None = None
    unresolved_intent: dict[str, Any] | None = None
    tool_trace: tuple[dict[str, Any], ...] = ()

def proposal_to_dict(proposal: ActionProposal) -> dict[str, Any]:
    return _jsonable(asdict(proposal))

def proposal_from_dict(data: dict[str, Any]) -> ActionProposal:
    memory_updates = tuple(
        MemoryFactDraft(
            kind=item["kind"],
            text=item["text"],
            confidence=item["confidence"],
            expires_at=_parse_optional_datetime(item.get("expires_at")),
        )
        for item in data.get("memory_updates", ())
    )
    execution_update = data.get("execution_update")
    execution_correction = data.get("execution_correction")
    plan_patch = data.get("plan_patch")
    fact_resolution = data.get("fact_resolution")
    week_proposal = data.get("week_proposal")
    pending_resolution = data.get("pending_resolution")
    return ActionProposal(
        type=data["type"],
        confidence=data["confidence"],
        user_intent_summary=data["user_intent_summary"],
        evidence=tuple(data.get("evidence", ())),
        answer_facts=tuple(data.get("answer_facts", ())),
        clarification_question=data.get("clarification_question"),
        memory_updates=memory_updates,
        execution_update=(
            ExecutionUpdateDraft(**execution_update) if execution_update is not None else None
        ),
        execution_correction=(
            ExecutionCorrectionDraft(**execution_correction)
            if execution_correction is not None
            else None
        ),
        plan_patch=_plan_patch_from_dict(plan_patch) if plan_patch is not None else None,
        fact_resolution=(
            FactResolutionDraft(
                fact_id=fact_resolution["fact_id"],
                reason=fact_resolution.get("reason", ""),
            )
            if fact_resolution is not None
            else None
        ),
        week_proposal=_week_proposal_from_dict(week_proposal) if week_proposal is not None else None,
        pending_resolution=(
            PendingResolutionDraft(
                pending_id=pending_resolution["pending_id"],
                decision=pending_resolution["decision"],
                note=pending_resolution.get("note", ""),
            )
            if pending_resolution is not None
            else None
        ),
        unresolved_intent=data.get("unresolved_intent"),
        tool_trace=tuple(data.get("tool_trace", ())),
    )

def _plan_patch_from_dict(data: dict[str, Any]) -> PlanPatchDraft:
    operations = tuple(
        PlanPatchOperation(
            kind=item["kind"],
            source_session_id=item["source_session_id"],
            target_date=_parse_optional_date(item.get("target_date")),
            target_session_id=item.get("target_session_id"),
            new_intensity_label=item.get("new_intensity_label"),
            new_sport=item.get("new_sport"),
            new_duration_min=item.get("new_duration_min"),
        )
        for item in data.get("operations", ())
    )
    return PlanPatchDraft(operations=operations, rationale=data["rationale"])

def _week_proposal_from_dict(data: dict[str, Any]) -> WeekProposalDraft:
    return WeekProposalDraft(
        week_start=data["week_start"],
        source=data["source"],
        week_load=data["week_load"],
        band=tuple(data["band"]),
        key_type=data["key_type"],
        sessions=tuple(dict(item) for item in data.get("sessions", ())),
    )

def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value

def _parse_optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None

def _parse_optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
