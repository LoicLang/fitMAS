---
summary: implementation plan for Decision Runtime Phase 3 CoachUnderstanding and legacy CoachDecision bridge
read_when:
  - implementing Decision Runtime Phase 3
  - replacing CoachDecision with CoachUnderstanding
  - modifying understanding contracts
  - isolating legacy CoachDecision, PlanPatch or MutationDecision behavior
  - preparing Phase 4 planning candidates from RequestedPlanChange
---

# Decision Runtime Phase 3 CoachUnderstanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CoachUnderstanding` the canonical comprehension artifact while keeping current runtime behavior stable.

**Architecture:** Phase 3 removes product meaning from the legacy `CoachDecision` shape by introducing typed understanding fields and a one-way legacy adapter. The new canonical code stays in `decision/`; any dependency on `fitmas.llm.CoachDecision`, `PlanPatch` or `MutationDecision` lives in `legacy/`. Conversation writes, planning commits and final replies remain driven by the existing path until Phase 4 can consume `RequestedPlanChange`.

**Tech Stack:** Python 3.13, dataclasses, Pydantic legacy models in `fitmas.llm`, pytest, AST/source architecture tests.

---

## Phase 3 Boundary

This phase is a comprehension migration, not a planning cutover.

Allowed:

- strengthen `decision/understanding.py`;
- create canonical typed objects for user signals, pending resolution and clarification need;
- create `backend/src/fitmas/legacy/` for migration adapters;
- map existing `CoachDecision | MutationDecision` objects to `CoachUnderstanding`;
- add architecture tests proving `decision/` stays free of legacy runtime contracts;
- optionally log shadow understanding from legacy decisions without changing user-visible behavior.

Forbidden:

- using `CoachUnderstanding` to commit a plan mutation;
- removing `CoachDecision` from `llm.py`;
- changing `conversation_prompt_modules.py` output schema;
- adding a new long prompt;
- moving `llm.py` into a package;
- creating `fitmas/llm/prompts/` while `backend/src/fitmas/llm.py` still exists;
- parsing free user text with regex or keywords;
- copying `fitmas_message` into `CoachUnderstanding`;
- carrying `PlanPatch`, `MutationDecision` or operation payloads inside canonical understanding objects.

## Files

- Modify: `backend/src/fitmas/decision/understanding.py`
  - Add `UserSignal`, `PendingResolution`, `ClarificationNeed` and stricter `CoachUnderstanding`.
- Modify: `backend/src/fitmas/decision/__init__.py`
  - Export the new pure understanding types.
- Create: `backend/src/fitmas/legacy/__init__.py`
  - Marks legacy migration code as isolated.
- Create: `backend/src/fitmas/legacy/coach_understanding_adapter.py`
  - Converts existing legacy LLM contracts to canonical `CoachUnderstanding`.
- Optional modify: `backend/src/fitmas/conversation_pipeline.py`
  - Add shadow-only observability call after `dependencies.decide(...)`, with no branch decisions based on the result.
- Modify: `tests/test_decision_types.py`
  - Cover the richer understanding dataclasses.
- Modify: `tests/test_decision_runtime_architecture.py`
  - Enforce that `decision/` does not import legacy, LLM runtime, tools, PlanPatch or MutationDecision.
- Create: `tests/test_coach_understanding_adapter.py`
  - Cover legacy-to-canonical mapping.
- Optional create: `tests/test_conversation_understanding_shadow.py`
  - Cover the shadow adapter wrapper if conversation logging is added.
- Modify after code lands: `docs/DECISION-RUNTIME-REFACTOR.md`
  - Mark Phase 3 local status.
- Modify after code lands: `docs/BUILD-ORDER.md`
  - Update the active roadmap status.

## Invariants

Copy these into every agent prompt for this phase:

```text
INVARIANTS FITMAS DECISION RUNTIME - PHASE 3

1. `CoachUnderstanding` is comprehension only.
2. It contains no final visible reply.
3. It contains no `PlanPatch`, no `MutationDecision`, no `CoachDecision`.
4. It contains no DB writes, no command results, no applied events.
5. `decision/` never imports `fitmas.llm`, `fitmas.plan_patch`, `fitmas.tools`, `conversation_pipeline` or `legacy/`.
6. Legacy conversion lives under `backend/src/fitmas/legacy/`.
7. The adapter reads only machine artifacts already emitted by the LLM, never free user text.
8. No regex or keyword heuristic is added on user text.
9. Existing runtime behavior is unchanged unless a shadow log is explicitly added.
10. Planning cutover waits for Phase 4.
```

## CTO Read

Phase 3 is the first place where the refactor can go sideways.

The dangerous shortcut is to ask the LLM for a smaller `CoachDecision` and call it done. That keeps the same power leak: the model still speaks, patches and commits conceptually. The useful move is different:

```text
legacy CoachDecision
-> isolated adapter
-> CoachUnderstanding
-> Phase 4 consumes RequestedPlanChange
```

This makes the next big slice possible without breaking dogfood.

Trade-offs:

- **Fast path:** adapter first, no prompt change. Low risk, gives tests and architecture pressure quickly.
- **Risky path:** rewrite `llm.py` prompt output now. High blast radius because `conversation_pipeline.py`, tools, final replies and tests still depend on `CoachDecision`.
- **Recommended path:** schema + adapter + shadow observation. Then Phase 4 makes planning consume `RequestedPlanChange`.

## Task 1: Strengthen Canonical Understanding Types

**Files:**
- Modify: `backend/src/fitmas/decision/understanding.py`
- Modify: `backend/src/fitmas/decision/__init__.py`
- Modify: `tests/test_decision_types.py`

- [ ] **Step 1: Write the failing tests**

Append these tests to `tests/test_decision_types.py`:

```python
def test_user_signal_pending_resolution_and_clarification_need_are_typed() -> None:
    from fitmas.decision import ClarificationNeed, PendingResolution, UserSignal

    signal = UserSignal(
        type="health",
        label="poor_sleep",
        status="new",
        severity="moderate",
        confidence=0.82,
        evidence="dormi 4h",
        payload={"affects": ("readiness",)},
    )
    pending = PendingResolution(
        type="modify_pending",
        reason="user changed target day",
        selected_candidate_id=None,
        requested_changes="vendredi plutot que mercredi",
        question=None,
    )
    clarification = ClarificationNeed(
        reason="target session ambiguous",
        missing_fields=("source_ref",),
        question_intent="identify_target_session",
    )

    assert signal.type == "health"
    assert signal.payload["affects"] == ("readiness",)
    assert pending.type == "modify_pending"
    assert clarification.missing_fields == ("source_ref",)


def test_coach_understanding_accepts_typed_signals_and_rejects_bad_confidence() -> None:
    from fitmas.decision import ClarificationNeed, CoachUnderstanding, UserSignal

    signal = UserSignal(
        type="availability",
        label="pool_closed",
        status="new",
        severity="unknown",
        confidence=0.77,
        evidence="piscine fermee",
        payload={"sport_type": "swimming"},
    )

    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.77,
        user_summary="piscine indisponible",
        extracted_signals=(signal,),
        requested_change=None,
        pending_resolution=None,
        clarification_need=None,
    )

    assert understanding.extracted_signals == (signal,)
    assert understanding.clarification_need is None

    with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
        CoachUnderstanding(
            intent="general_answer",
            confidence=1.3,
            user_summary="bad confidence",
            extracted_signals=(),
            requested_change=None,
            pending_resolution=None,
            clarification_need=ClarificationNeed(
                reason="not used",
                missing_fields=(),
                question_intent="none",
            ),
        )
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_decision_types.py::test_user_signal_pending_resolution_and_clarification_need_are_typed tests/test_decision_types.py::test_coach_understanding_accepts_typed_signals_and_rejects_bad_confidence -q
```

Expected:

```text
FAILED ... ImportError: cannot import name 'ClarificationNeed'
```

- [ ] **Step 3: Implement the canonical types**

Replace `backend/src/fitmas/decision/understanding.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


CoachIntent = Literal[
    "close",
    "general_answer",
    "plan_lookup",
    "execution_report",
    "health_signal",
    "availability_signal",
    "plan_change",
    "pending_response",
    "clarification",
]

RequestedPlanChangeKind = Literal[
    "move",
    "swap",
    "lighten",
    "replace",
    "create",
    "remove_optional",
    "unknown",
]

UserSignalType = Literal[
    "health",
    "availability",
    "preference",
    "execution",
    "readiness",
    "planning",
    "pending",
    "other",
]

PendingResolutionType = Literal[
    "accept_pending",
    "reject_pending",
    "modify_pending",
    "ignore",
    "needs_clarification",
]


def _validate_confidence(value: float) -> None:
    if value < 0.0 or value > 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class UserSignal:
    type: UserSignalType
    label: str
    status: str
    severity: str
    confidence: float
    evidence: str | None
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class PendingResolution:
    type: PendingResolutionType
    reason: str | None
    selected_candidate_id: str | None
    requested_changes: str | None
    question: str | None


@dataclass(frozen=True, slots=True)
class ClarificationNeed:
    reason: str
    missing_fields: tuple[str, ...]
    question_intent: str


@dataclass(frozen=True, slots=True)
class RequestedPlanChange:
    kind: RequestedPlanChangeKind
    source_ref: str | None
    target_ref: str | None
    desired_sport: str | None
    desired_duration_min: int | None
    desired_intensity: str | None
    reason: str
    risk_signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoachUnderstanding:
    intent: CoachIntent
    confidence: float
    user_summary: str
    extracted_signals: tuple[UserSignal, ...]
    requested_change: RequestedPlanChange | None
    pending_resolution: PendingResolution | None
    clarification_need: ClarificationNeed | None

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)
```

- [ ] **Step 4: Export the new types**

Modify `backend/src/fitmas/decision/__init__.py`:

```python
from .understanding import (
    ClarificationNeed,
    CoachUnderstanding,
    PendingResolution,
    RequestedPlanChange,
    UserSignal,
)
```

Add these names to `__all__`:

```python
    "ClarificationNeed",
    "PendingResolution",
    "UserSignal",
```

- [ ] **Step 5: Run the type tests**

Run:

```bash
pytest tests/test_decision_types.py -q
```

Expected:

```text
8 passed
```

- [ ] **Step 6: Commit the schema slice**

```bash
git add backend/src/fitmas/decision/understanding.py backend/src/fitmas/decision/__init__.py tests/test_decision_types.py
git commit -m "refactor: strengthen coach understanding types"
```

## Task 2: Add Legacy CoachDecision Adapter

**Files:**
- Create: `backend/src/fitmas/legacy/__init__.py`
- Create: `backend/src/fitmas/legacy/coach_understanding_adapter.py`
- Create: `tests/test_coach_understanding_adapter.py`

- [ ] **Step 1: Write adapter tests**

Create `tests/test_coach_understanding_adapter.py`:

```python
from __future__ import annotations

from fitmas.legacy.coach_understanding_adapter import coach_decision_to_understanding
from fitmas.llm import (
    AcceptPendingResolution,
    AvailabilityConstraintAction,
    CoachDecision,
    ExecutionUpdateAction,
    HealthSignalAction,
    ModifyPendingResolution,
    MutationDecision,
)
from fitmas.plan_patch import PlanPatch, PlanPatchOperation


def test_adapter_maps_health_memory_action_without_visible_reply() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="fatigue signalee sans mutation",
        fitmas_message="Ancien message visible qui ne doit pas etre copie.",
        memory_actions=(
            HealthSignalAction(
                type="record_health_signal",
                health_signal="mauvais sommeil",
                signal_kind="sleep",
                severity="moderate",
                status="new",
                confidence=0.84,
                evidence="j'ai dormi 4h",
            ),
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "health_signal"
    assert understanding.user_summary == "fatigue signalee sans mutation"
    assert understanding.extracted_signals[0].type == "health"
    assert understanding.extracted_signals[0].label == "sleep"
    assert understanding.extracted_signals[0].payload["health_signal"] == "mauvais sommeil"
    assert "Ancien message visible" not in repr(understanding)


def test_adapter_maps_availability_and_execution_actions() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="disponibilite et execution captees",
        fitmas_message="Message legacy ignore.",
        memory_actions=(
            AvailabilityConstraintAction(
                type="record_availability",
                window_text="piscine fermee deux semaines",
                availability="unavailable",
                sport_type="swimming",
                starts_on="2026-05-14",
                ends_on="2026-05-28",
                confidence=0.8,
                evidence="piscine fermee",
            ),
        ),
        execution_actions=(
            ExecutionUpdateAction(
                type="record_execution_update",
                target_ref="seance d'hier",
                status="not_completed",
                completed=False,
                sport_type="running",
                confidence=0.79,
                evidence="je l'ai ratee",
            ),
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "execution_report"
    assert [signal.type for signal in understanding.extracted_signals] == ["availability", "execution"]
    assert understanding.extracted_signals[0].payload["sport_type"] == "swimming"
    assert understanding.extracted_signals[1].payload["target_ref"] == "seance d'hier"


def test_adapter_maps_pending_resolution() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="pending modifiee",
        fitmas_message="Message legacy ignore.",
        pending_resolution=ModifyPendingResolution(
            type="modify_pending",
            requested_changes="vendredi plutot que mercredi",
            reason="changement de disponibilite",
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "pending_response"
    assert understanding.pending_resolution is not None
    assert understanding.pending_resolution.type == "modify_pending"
    assert understanding.pending_resolution.requested_changes == "vendredi plutot que mercredi"


def test_adapter_maps_plan_patch_to_requested_change_without_carrying_patch() -> None:
    decision = CoachDecision(
        response_type="plan_patch",
        rationale="deplacement demande",
        fitmas_message="Message legacy ignore.",
        plan_patch=PlanPatch(
            coach_message="Message patch ignore.",
            operations=(
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=42,
                    target_date="2026-05-15",
                    rationale="fatigue",
                ),
            ),
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "plan_change"
    assert understanding.requested_change is not None
    assert understanding.requested_change.kind == "move"
    assert understanding.requested_change.source_ref == "session_id:42"
    assert understanding.requested_change.target_ref == "date:2026-05-15"
    assert "PlanPatch" not in repr(understanding)


def test_adapter_maps_legacy_mutation_decision_to_requested_change() -> None:
    decision = MutationDecision(
        mutation_type="lighten_day",
        target_session_id=7,
        target_date=None,
        from_day=None,
        to_day=None,
        rationale="fatigue",
        fitmas_message="Message legacy ignore.",
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "plan_change"
    assert understanding.requested_change is not None
    assert understanding.requested_change.kind == "lighten"
    assert understanding.requested_change.source_ref == "session_id:7"
    assert understanding.requested_change.reason == "fatigue"


def test_adapter_maps_accept_pending_candidate_choice() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="choix candidat",
        fitmas_message="Message legacy ignore.",
        pending_resolution=AcceptPendingResolution(
            type="accept_pending",
            reason="option choisie",
            selected_candidate_id="candidate_b",
        ),
    )

    understanding = coach_decision_to_understanding(decision)

    assert understanding.intent == "pending_response"
    assert understanding.pending_resolution is not None
    assert understanding.pending_resolution.selected_candidate_id == "candidate_b"
```

- [ ] **Step 2: Run the adapter tests and verify they fail**

Run:

```bash
pytest tests/test_coach_understanding_adapter.py -q
```

Expected:

```text
FAILED ... ModuleNotFoundError: No module named 'fitmas.legacy'
```

- [ ] **Step 3: Create the legacy package marker**

Create `backend/src/fitmas/legacy/__init__.py`:

```python
"""Legacy migration adapters for the Decision Runtime refactor."""
```

- [ ] **Step 4: Implement the adapter**

Create `backend/src/fitmas/legacy/coach_understanding_adapter.py`:

```python
from __future__ import annotations

from typing import Any, Mapping

from fitmas.decision import (
    CoachUnderstanding,
    PendingResolution,
    RequestedPlanChange,
    UserSignal,
)
from fitmas.llm import CoachDecision, MutationDecision


def coach_decision_to_understanding(decision: CoachDecision | MutationDecision) -> CoachUnderstanding:
    signals = _signals_from_decision(decision)
    pending_resolution = _pending_resolution_from_decision(decision)
    requested_change = _requested_change_from_decision(decision)
    intent = _intent_from_decision(
        decision,
        signals=signals,
        pending_resolution=pending_resolution,
        requested_change=requested_change,
    )
    confidence = _confidence_from_signals(signals)

    return CoachUnderstanding(
        intent=intent,
        confidence=confidence,
        user_summary=_rationale(decision),
        extracted_signals=signals,
        requested_change=requested_change,
        pending_resolution=pending_resolution,
        clarification_need=None,
    )


def _rationale(decision: CoachDecision | MutationDecision) -> str:
    return str(getattr(decision, "rationale", "") or "").strip()


def _confidence_from_signals(signals: tuple[UserSignal, ...]) -> float:
    if not signals:
        return 0.7
    return min(1.0, max(0.0, sum(signal.confidence for signal in signals) / len(signals)))


def _signals_from_decision(decision: CoachDecision | MutationDecision) -> tuple[UserSignal, ...]:
    if isinstance(decision, MutationDecision):
        return ()
    signals: list[UserSignal] = []
    for action in tuple(getattr(decision, "memory_actions", ()) or ()):
        signal = _signal_from_memory_action(action)
        if signal is not None:
            signals.append(signal)
    for action in tuple(getattr(decision, "execution_actions", ()) or ()):
        signals.append(_signal_from_execution_action(action))
    return tuple(signals)


def _signal_from_memory_action(action: Any) -> UserSignal | None:
    action_type = str(getattr(action, "type", "") or "")
    payload = _model_payload(action)

    if action_type == "record_health_signal":
        return UserSignal(
            type="health",
            label=str(payload.get("signal_kind") or "other"),
            status=str(payload.get("status") or "unknown"),
            severity=str(payload.get("severity") or "unknown"),
            confidence=float(payload.get("confidence") or 0.75),
            evidence=_optional_str(payload.get("evidence") or payload.get("health_signal")),
            payload=payload,
        )
    if action_type == "record_availability":
        return UserSignal(
            type="availability",
            label=str(payload.get("availability") or "unknown"),
            status=str(payload.get("availability") or "unknown"),
            severity="unknown",
            confidence=float(payload.get("confidence") or 0.75),
            evidence=_optional_str(payload.get("evidence") or payload.get("window_text")),
            payload=payload,
        )
    if action_type == "record_preference":
        return UserSignal(
            type="preference",
            label=str(payload.get("polarity") or "unknown"),
            status=str(payload.get("polarity") or "unknown"),
            severity="unknown",
            confidence=float(payload.get("confidence") or 0.75),
            evidence=_optional_str(payload.get("evidence") or payload.get("preference")),
            payload=payload,
        )
    return None


def _signal_from_execution_action(action: Any) -> UserSignal:
    payload = _model_payload(action)
    return UserSignal(
        type="execution",
        label=str(payload.get("status") or "unknown"),
        status=str(payload.get("status") or "unknown"),
        severity="unknown",
        confidence=float(payload.get("confidence") or 0.75),
        evidence=_optional_str(payload.get("evidence") or payload.get("target_ref")),
        payload=payload,
    )


def _pending_resolution_from_decision(decision: CoachDecision | MutationDecision) -> PendingResolution | None:
    if isinstance(decision, MutationDecision):
        return None
    resolution = getattr(decision, "pending_resolution", None)
    if resolution is None:
        return None
    payload = _model_payload(resolution)
    return PendingResolution(
        type=str(payload.get("type") or "ignore"),
        reason=_optional_str(payload.get("reason")),
        selected_candidate_id=_optional_str(payload.get("selected_candidate_id")),
        requested_changes=_optional_str(payload.get("requested_changes")),
        question=_optional_str(payload.get("question")),
    )


def _requested_change_from_decision(decision: CoachDecision | MutationDecision) -> RequestedPlanChange | None:
    if isinstance(decision, MutationDecision):
        return _requested_change_from_mutation_decision(decision)
    response_type = str(getattr(decision, "response_type", "") or "")
    if response_type == "mutation_decision" and getattr(decision, "mutation_decision", None) is not None:
        return _requested_change_from_mutation_decision(decision.mutation_decision)
    if response_type in {"plan_patch", "requires_confirmation"} and getattr(decision, "plan_patch", None) is not None:
        return _requested_change_from_plan_patch(decision.plan_patch, reason=_rationale(decision))
    return None


def _requested_change_from_mutation_decision(decision: MutationDecision) -> RequestedPlanChange | None:
    mutation_type = str(getattr(decision, "mutation_type", "") or "")
    if mutation_type == "no_change":
        return None
    return RequestedPlanChange(
        kind=_kind_from_mutation_type(mutation_type),
        source_ref=_source_ref_from_target(getattr(decision, "target_session_id", None)),
        target_ref=_target_ref_from_mutation(decision),
        desired_sport=_optional_str(getattr(decision, "new_sport_type", None)),
        desired_duration_min=getattr(decision, "new_duration_min", None),
        desired_intensity=_optional_str(getattr(decision, "new_intensity", None)),
        reason=_rationale(decision),
        risk_signals=(),
    )


def _requested_change_from_plan_patch(patch: Any, *, reason: str) -> RequestedPlanChange:
    operations = tuple(getattr(patch, "operations", ()) or ())
    first = operations[0] if operations else None
    operation_types = {str(getattr(operation, "operation_type", "") or "") for operation in operations}

    return RequestedPlanChange(
        kind=_kind_from_operation_types(operation_types),
        source_ref=_source_ref_from_target(getattr(first, "target_session_id", None)),
        target_ref=_target_ref_from_operation(first),
        desired_sport=_optional_str(getattr(first, "new_sport_type", None)),
        desired_duration_min=getattr(first, "new_duration_min", None),
        desired_intensity=_optional_str(getattr(first, "new_intensity", None)),
        reason=reason,
        risk_signals=(),
    )


def _kind_from_mutation_type(mutation_type: str) -> str:
    return {
        "move_session": "move",
        "swap_sessions": "swap",
        "lighten_day": "lighten",
        "replace_session": "replace",
        "update_session": "replace",
        "create_session": "create",
    }.get(mutation_type, "unknown")


def _kind_from_operation_types(operation_types: set[str]) -> str:
    if len(operation_types) != 1:
        return "unknown"
    return _kind_from_mutation_type(next(iter(operation_types)))


def _source_ref_from_target(target_session_id: Any) -> str | None:
    if target_session_id is None:
        return None
    return f"session_id:{target_session_id}"


def _target_ref_from_mutation(decision: MutationDecision) -> str | None:
    target_date = _optional_str(getattr(decision, "target_date", None))
    if target_date:
        return f"date:{target_date}"
    to_day = _optional_str(getattr(decision, "to_day", None))
    if to_day:
        return f"day:{to_day}"
    second_session_id = getattr(decision, "second_session_id", None)
    if second_session_id is not None:
        return f"session_id:{second_session_id}"
    return None


def _target_ref_from_operation(operation: Any) -> str | None:
    if operation is None:
        return None
    target_date = _optional_str(getattr(operation, "target_date", None))
    if target_date:
        return f"date:{target_date}"
    second_session_id = getattr(operation, "second_session_id", None)
    if second_session_id is not None:
        return f"session_id:{second_session_id}"
    return None


def _intent_from_decision(
    decision: CoachDecision | MutationDecision,
    *,
    signals: tuple[UserSignal, ...],
    pending_resolution: PendingResolution | None,
    requested_change: RequestedPlanChange | None,
) -> str:
    if pending_resolution is not None:
        return "pending_response"
    if requested_change is not None:
        return "plan_change"
    if any(signal.type == "execution" for signal in signals):
        return "execution_report"
    if any(signal.type == "health" for signal in signals):
        return "health_signal"
    if any(signal.type == "availability" for signal in signals):
        return "availability_signal"
    if isinstance(decision, CoachDecision) and decision.response_type in {"reply", "no_change"}:
        return "general_answer"
    return "general_answer"


def _model_payload(value: Any) -> Mapping[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, Mapping):
        return {key: item for key, item in value.items() if item is not None}
    return {}


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
```

- [ ] **Step 5: Run the adapter tests**

Run:

```bash
pytest tests/test_coach_understanding_adapter.py -q
```

Expected:

```text
6 passed
```

- [ ] **Step 6: Commit the adapter slice**

```bash
git add backend/src/fitmas/legacy tests/test_coach_understanding_adapter.py
git commit -m "refactor: add legacy coach understanding adapter"
```

## Task 3: Add Architecture Guardrails For Phase 3

**Files:**
- Modify: `tests/test_decision_runtime_architecture.py`

- [ ] **Step 1: Write the guardrail tests**

Add this import near the top of `tests/test_decision_runtime_architecture.py`:

```python
from dataclasses import fields
```

Add this helper below `_imports`:

```python

def _field_names(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}
```

Append these tests:

```python

def test_legacy_understanding_adapter_is_only_legacy_module_importing_llm_contracts() -> None:
    legacy = ROOT / "backend" / "src" / "fitmas" / "legacy"
    allowed = {
        legacy / "coach_understanding_adapter.py",
        legacy / "understanding_shadow.py",
    }
    forbidden_modules = {
        "fitmas.llm",
        "fitmas.plan_patch",
        "fitmas.conversation_pipeline",
    }
    offenders: list[str] = []

    for path in sorted(legacy.glob("*.py")):
        if path.name == "__init__.py" or path in allowed:
            continue
        imports = _imports(path)
        for module in imports:
            if module in forbidden_modules:
                offenders.append(f"{path.name}: {module}")

    assert offenders == []


def test_decision_understanding_has_no_legacy_contract_fields() -> None:
    from fitmas.decision import CoachUnderstanding, PendingResolution, RequestedPlanChange, UserSignal

    checked = (CoachUnderstanding, PendingResolution, RequestedPlanChange, UserSignal)
    forbidden = {
        "fitmas_message",
        "reply_text",
        "final_reply",
        "plan_patch",
        "mutation_decision",
        "coach_decision",
        "operations",
        "command",
        "event_id",
    }

    for cls in checked:
        assert _field_names(cls).isdisjoint(forbidden), cls
```

Replace the existing `test_decision_package_does_not_import_legacy_runtime_contracts` with this stricter version:

```python
def test_decision_package_stays_free_of_legacy_understanding_adapter() -> None:
    forbidden_exact = {
        "fitmas.legacy",
        "fitmas.legacy.coach_understanding_adapter",
        "fitmas.llm",
        "fitmas.plan_patch",
        "fitmas.conversation_pipeline",
    }
    offenders: list[str] = []

    for path in _python_files():
        for module in _imports(path):
            if module in forbidden_exact or module.startswith("fitmas.legacy."):
                offenders.append(f"{path.name}: {module}")

    assert offenders == []
```

- [ ] **Step 2: Run the architecture tests**

Run:

```bash
pytest tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
9 passed
```

- [ ] **Step 3: Commit the guardrail slice**

```bash
git add tests/test_decision_runtime_architecture.py
git commit -m "test: guard coach understanding boundaries"
```

## Task 4: Add Shadow Understanding Observation

**Files:**
- Create: `backend/src/fitmas/legacy/understanding_shadow.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Create: `tests/test_conversation_understanding_shadow.py`

This task is recommended only after Tasks 1-3 pass. It adds observability without using understanding to choose behavior.

- [ ] **Step 1: Write shadow tests**

Create `tests/test_conversation_understanding_shadow.py`:

```python
from __future__ import annotations

from fitmas.legacy.understanding_shadow import shadow_understanding_from_legacy_decision
from fitmas.llm import CoachDecision


def test_shadow_understanding_returns_none_for_missing_decision() -> None:
    assert shadow_understanding_from_legacy_decision(user_id=1, decision=None) is None


def test_shadow_understanding_converts_legacy_decision_without_raising() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="lecture simple",
        fitmas_message="Message legacy ignore.",
    )

    understanding = shadow_understanding_from_legacy_decision(user_id=1, decision=decision)

    assert understanding is not None
    assert understanding.intent == "general_answer"
    assert understanding.user_summary == "lecture simple"
```

- [ ] **Step 2: Run the shadow tests and verify they fail**

Run:

```bash
pytest tests/test_conversation_understanding_shadow.py -q
```

Expected:

```text
FAILED ... ModuleNotFoundError: No module named 'fitmas.legacy.understanding_shadow'
```

- [ ] **Step 3: Implement the shadow wrapper**

Create `backend/src/fitmas/legacy/understanding_shadow.py`:

```python
from __future__ import annotations

import logging
from typing import Any

from fitmas.decision import CoachUnderstanding
from fitmas.legacy.coach_understanding_adapter import coach_decision_to_understanding

logger = logging.getLogger(__name__)


def shadow_understanding_from_legacy_decision(*, user_id: int, decision: Any) -> CoachUnderstanding | None:
    if decision is None:
        return None
    try:
        understanding = coach_decision_to_understanding(decision)
    except Exception as exc:
        logger.warning(
            "decision_runtime.shadow_understanding_failed user=%s error=%s",
            user_id,
            str(exc)[:180],
            exc_info=True,
        )
        return None

    logger.info(
        "decision_runtime.shadow_understanding user=%s intent=%s confidence=%.2f signals=%s requested_change=%s pending=%s",
        user_id,
        understanding.intent,
        understanding.confidence,
        len(understanding.extracted_signals),
        1 if understanding.requested_change is not None else 0,
        1 if understanding.pending_resolution is not None else 0,
    )
    return understanding
```

- [ ] **Step 4: Wire the shadow call after the LLM decision**

In `backend/src/fitmas/conversation_pipeline.py`, add the import:

```python
from fitmas.legacy.understanding_shadow import shadow_understanding_from_legacy_decision
```

Immediately after this existing block:

```python
    decision = dependencies.decide(
        user_text=payload.text,
        plan_summary=state.plan_summary,
        timeline_summary=state.timeline_summary,
        execution_summary=execution_summary_for_prompt(conversation_context),
        temporal_summary=temporal_summary_for_prompt(conversation_context),
        activity_claim_summary=claim_summary,
        signal_summary=signal_summary_for_prompt(conversation_context),
        conversation_history=state.conversation_history[:-1],
        coach_context=coach_context_payload,
        remembered_facts=state.active_facts,
        time_context=conversation_context.time_context,
        tool_context=tool_context,
    )
```

add:

```python
    shadow_understanding_from_legacy_decision(user_id=user.id, decision=decision)
```

Do not assign the result to a variable used later in the function.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
pytest tests/test_conversation_understanding_shadow.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
11 passed
```

- [ ] **Step 6: Commit the shadow slice**

```bash
git add backend/src/fitmas/legacy/understanding_shadow.py backend/src/fitmas/conversation_pipeline.py tests/test_conversation_understanding_shadow.py
git commit -m "refactor: shadow legacy coach understanding"
```

## Task 5: Documentation And Verification

**Files:**
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] **Step 1: Update Decision Runtime status**

In `docs/DECISION-RUNTIME-REFACTOR.md`, extend the implementation status section with:

```markdown
Livres en Phase 3 initiale :

- `CoachUnderstanding` renforce avec `UserSignal`, `PendingResolution` et
  `ClarificationNeed` ;
- conversion legacy isolee dans `backend/src/fitmas/legacy/coach_understanding_adapter.py` ;
- `decision/` reste libre de `fitmas.llm`, `PlanPatch`, `MutationDecision`,
  tools, DB writes et reponses visibles ;
- shadow understanding possible depuis `conversation_pipeline.py` sans changer
  les branches runtime ;
- aucun prompt, writer, commit planning ou reply composer live n'a ete migre.
```

- [ ] **Step 2: Update build order**

In `docs/BUILD-ORDER.md`, update the local status with:

```markdown
- Phase 3 initiale livree localement :
  - `CoachUnderstanding` porte des signaux et resolutions typed ;
  - `CoachDecision -> CoachUnderstanding` existe uniquement dans `legacy/` ;
  - le runtime peut logger un shadow understanding sans l'utiliser pour write,
    reply ou commit ;
  - la bascule planning reste reservee a Phase 4.
```

- [ ] **Step 3: Run full targeted verification**

Run:

```bash
pytest tests/test_decision_types.py tests/test_decision_runtime_architecture.py tests/test_coach_understanding_adapter.py tests/test_conversation_understanding_shadow.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 4: Run the existing relevant legacy tests**

Run:

```bash
pytest tests/test_llm_tools.py tests/test_core_flows.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected:

```text
full suite passes with the repository's existing skipped tests count
```

- [ ] **Step 6: Run docs list**

Run:

```bash
./scripts/docs:list
```

Expected:

```text
The new Phase 3 plan appears with its summary and read_when hints.
```

- [ ] **Step 7: Commit docs and verification status**

```bash
git add docs/DECISION-RUNTIME-REFACTOR.md docs/BUILD-ORDER.md docs/superpowers/plans/2026-05-14-decision-runtime-phase-3-coach-understanding.md
git commit -m "docs: plan decision runtime phase 3"
```

## Acceptance Criteria

Phase 3 is complete when:

- `CoachUnderstanding` no longer has `Any` for signals or pending resolution;
- `CoachUnderstanding` has no visible reply field;
- `RequestedPlanChange` has no patch or operation field;
- legacy `CoachDecision` conversion exists only in `fitmas.legacy`;
- `decision/` does not import `fitmas.legacy`, `fitmas.llm`, `fitmas.plan_patch`, tools, DB write services or conversation runtime;
- adapter tests cover health, availability, execution, pending, PlanPatch and MutationDecision inputs;
- any shadow runtime call is observability-only;
- existing conversation behavior remains stable;
- docs state clearly that Phase 4 owns the real planning cutover.

## What This Unlocks

Phase 4 can stop reading `decision.plan_patch` and start consuming:

```text
CoachUnderstanding.requested_change
-> ReferenceResolver
-> CandidateBuilder
-> Evaluator
-> Policy
-> PlanningCommandService
```

That is where the work becomes materially larger: references, candidates, simulation, pending policy and writes all have to line up behind one path.
