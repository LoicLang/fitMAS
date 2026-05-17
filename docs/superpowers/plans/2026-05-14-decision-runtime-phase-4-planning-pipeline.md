---
summary: implementation plan for Decision Runtime Phase 4 canonical planning pipeline
read_when:
  - implementing Decision Runtime Phase 4
  - creating domain/planning modules
  - replacing direct PlanPatch or MutationDecision runtime paths
  - routing RequestedPlanChange through candidates, evaluator, policy and PlanningCommandService
  - keeping conversation_pipeline from growing new planning branches
---

# Decision Runtime Phase 4 Planning Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route planning changes through one backend-owned pipeline: `RequestedPlanChange -> ReferenceResolver -> CandidateBuilder -> Evaluator -> Policy -> PlanningCommandService`.

**Architecture:** Phase 4 creates the target `domain/planning/` bounded context without moving the old flat modules yet. Existing `PlanPatch`, evaluator, reviewer, policy and `PlanMutationService` are reused behind new domain entrypoints. `conversation_pipeline.py` gets one thin adapter call in the existing planning area; no new prompt, no free-text parsing, no second reply system.

**Tech Stack:** Python 3.13, dataclasses, Pydantic `PlanPatch`, SQLAlchemy Session only in evaluator/command service boundaries, pytest, existing candidate/evaluator/policy/reviewer modules.

**Status 2026-05-14:** implemented locally. The conversation call is guarded by
`FITMAS_PLANNING_RUNTIME_CUTOVER=1` because direct cutover changed existing
dogfood semantics before Phase 5 ReplyComposer. The domain pipeline, writer,
adapter and architecture tests are present and passing.

---

## Phase 4 Boundary

This phase is the first behavior-sensitive planning cutover.

Allowed:

- create `backend/src/fitmas/domain/planning/`;
- reuse existing `PlanPatch`, `PlanPatchCandidate`, evaluator, reviewer and policy;
- resolve only typed refs from `RequestedPlanChange`, such as `session_id:42`, `date:2026-05-15`, `day:friday`;
- build backend-owned candidates from DB/session truth;
- write planning changes only through `PlanningCommandService`;
- add one conversation adapter call before old direct planning branches;
- keep old flat modules as compatibility internals.

Forbidden:

- parsing free user text;
- adding or editing prompts;
- asking the LLM to produce `PlanPatch`;
- creating `llm/prompts/`;
- moving `llm.py`;
- deleting legacy `PlanPatch` or `MutationDecision` paths before the cutover tests prove replacement behavior;
- adding another branch inside `conversation_pipeline.py` for each planning case;
- writing DB state outside `PlanningCommandService` for new Phase 4 code;
- changing memory/execution action behavior.

## Repo Target For This Phase

Create this package now:

```text
backend/src/fitmas/domain/
  __init__.py
  planning/
    __init__.py
    models.py
    reference_resolver.py
    candidate_builder.py
    evaluator.py
    policy.py
    mutation_service.py
    decision_service.py
```

Leave these existing modules in place as legacy support for now:

```text
backend/src/fitmas/plan_patch.py
backend/src/fitmas/plan_patch_candidates.py
backend/src/fitmas/plan_patch_candidate_evaluator.py
backend/src/fitmas/plan_patch_candidate_reviewer.py
backend/src/fitmas/plan_patch_adaptation_policy.py
backend/src/fitmas/plan_mutation_service.py
```

Do not move them in this phase. The target repo organization starts with wrappers, then later migration.

## Invariants

Copy these into every agent prompt for this phase:

```text
INVARIANTS FITMAS DECISION RUNTIME - PHASE 4

1. The LLM does not produce PlanPatch as authority.
2. Planning starts from CoachUnderstanding.requested_change.
3. ReferenceResolver only resolves typed refs and DB/session truth.
4. CandidateBuilder constructs PlanPatch candidates; it never writes.
5. Evaluator simulates and scores candidates; it never writes.
6. Policy decides commit / pending_confirmation / pending_choice / block; it never writes.
7. PlanningCommandService is the only new Phase 4 planning writer.
8. Reply text remains the existing final_reply path until Phase 5.
9. conversation_pipeline may call one adapter, not grow per-case planning branches.
10. WeeklyPlan/DayPlan remain out of runtime planning decisions.
```

## CTO Read

This is where work becomes materially bigger.

Phase 0-3 were mostly architecture scaffolding. Phase 4 changes the planning power model:

```text
old: LLM returns PlanPatch or MutationDecision, pipeline validates after
new: LLM returns RequestedPlanChange, backend builds and arbitrates candidates
```

The risky shortcut is trying to delete every old planning branch at once. Do not. The controlled move:

1. build the new domain pipeline;
2. test it independently;
3. wire one adapter before the old direct planning branches;
4. keep old branches as fallback while tests pin behavior;
5. only then tighten architecture tests.

## Task 1: Domain Planning Models And Package Boundary

**Files:**
- Create: `backend/src/fitmas/domain/__init__.py`
- Create: `backend/src/fitmas/domain/planning/__init__.py`
- Create: `backend/src/fitmas/domain/planning/models.py`
- Create: `tests/test_domain_planning_models.py`
- Modify: `tests/test_decision_runtime_architecture.py`

- [ ] **Step 1: Write model tests**

Create `tests/test_domain_planning_models.py`:

```python
from __future__ import annotations

from datetime import date

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.models import (
    PlanChangeReference,
    PlanningCandidateSet,
    PlanningDecisionResult,
    ResolvedPlanChange,
)


def test_resolved_plan_change_keeps_requested_change_and_typed_refs() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="date:2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=("fatigue",),
    )
    resolved = ResolvedPlanChange(
        requested_change=requested,
        source=PlanChangeReference(kind="session", raw="session_id:42", session_id=42, date=None),
        target=PlanChangeReference(kind="date", raw="date:2026-05-15", session_id=None, date=date(2026, 5, 15)),
        warnings=(),
    )

    assert resolved.kind == "move"
    assert resolved.source.session_id == 42
    assert resolved.target.date == date(2026, 5, 15)
    assert resolved.reason == "fatigue"


def test_planning_candidate_set_is_backend_owned() -> None:
    candidate_set = PlanningCandidateSet(candidates=(), backend_candidate_patches={})

    assert candidate_set.candidates == ()
    assert candidate_set.backend_candidate_patches == {}


def test_planning_decision_result_has_no_reply_text() -> None:
    result = PlanningDecisionResult(
        kind="block",
        selected_candidate_id=None,
        candidate_options=(),
        reason="Aucune option valide.",
        policy_decision=None,
        selected_patch=None,
        evaluated_candidates=(),
        command_result=None,
        pending_confirmation_id=None,
    )

    assert result.kind == "block"
    assert not hasattr(result, "fitmas_message")
    assert not hasattr(result, "reply_text")
```

- [ ] **Step 2: Run model tests and verify they fail**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_models.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.domain'
```

- [ ] **Step 3: Create package markers**

Create `backend/src/fitmas/domain/__init__.py`:

```python
"""Domain bounded contexts for FitMAS."""
```

Create `backend/src/fitmas/domain/planning/__init__.py`:

```python
from .models import (
    PlanChangeReference,
    PlanningCandidateSet,
    PlanningDecisionResult,
    ResolvedPlanChange,
)

__all__ = [
    "PlanChangeReference",
    "PlanningCandidateSet",
    "PlanningDecisionResult",
    "ResolvedPlanChange",
]
```

- [ ] **Step 4: Implement planning models**

Create `backend/src/fitmas/domain/planning/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Mapping

from fitmas.decision import RequestedPlanChange
from fitmas.plan_patch import PlanPatch
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision
from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate
from fitmas.plan_patch_candidates import PlanPatchCandidate
from fitmas.plan_mutation_service import PlanPatchServiceResult

ReferenceKind = Literal["session", "date", "unknown"]
PlanningDecisionKind = Literal["commit", "pending_confirmation", "pending_choice", "block"]


@dataclass(frozen=True, slots=True)
class PlanChangeReference:
    kind: ReferenceKind
    raw: str | None
    session_id: int | None
    date: date | None


@dataclass(frozen=True, slots=True)
class ResolvedPlanChange:
    requested_change: RequestedPlanChange
    source: PlanChangeReference
    target: PlanChangeReference
    warnings: tuple[str, ...]

    @property
    def kind(self) -> str:
        return self.requested_change.kind

    @property
    def reason(self) -> str:
        return self.requested_change.reason


@dataclass(frozen=True, slots=True)
class PlanningCandidateSet:
    candidates: tuple[PlanPatchCandidate, ...]
    backend_candidate_patches: Mapping[str, PlanPatch]


@dataclass(frozen=True, slots=True)
class PlanningCommandResult:
    status: Literal["applied", "pending", "blocked", "skipped"]
    event_count: int
    pending_confirmation_id: int | None
    service_result: PlanPatchServiceResult | None
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PlanningDecisionResult:
    kind: PlanningDecisionKind
    selected_candidate_id: str | None
    candidate_options: tuple[str, ...]
    reason: str
    policy_decision: AdaptationPolicyDecision | None
    selected_patch: PlanPatch | None
    evaluated_candidates: tuple[EvaluatedPlanPatchCandidate, ...]
    command_result: PlanningCommandResult | None
    pending_confirmation_id: int | None
```

- [ ] **Step 5: Export `PlanningCommandResult`**

Modify `backend/src/fitmas/domain/planning/__init__.py`:

```python
from .models import (
    PlanChangeReference,
    PlanningCandidateSet,
    PlanningCommandResult,
    PlanningDecisionResult,
    ResolvedPlanChange,
)

__all__ = [
    "PlanChangeReference",
    "PlanningCandidateSet",
    "PlanningCommandResult",
    "PlanningDecisionResult",
    "ResolvedPlanChange",
]
```

- [ ] **Step 6: Add architecture test for new package**

Append to `tests/test_decision_runtime_architecture.py`:

```python
def test_domain_planning_package_exists_without_free_text_parsers() -> None:
    planning = ROOT / "backend" / "src" / "fitmas" / "domain" / "planning"
    assert planning.exists()
    forbidden_tokens = (
        "user_text",
        "payload.text",
        "re.search",
        "re.match",
        ".lower() in",
    )
    offenders: list[str] = []
    for path in sorted(planning.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in source:
                offenders.append(f"{path.name}: {token}")
    assert offenders == []
```

- [ ] **Step 7: Run tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_models.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 8: Commit**

```bash
git add backend/src/fitmas/domain tests/test_domain_planning_models.py tests/test_decision_runtime_architecture.py
git commit -m "refactor: add planning domain model boundary"
```

## Task 2: ReferenceResolver From Typed Refs Only

**Files:**
- Create: `backend/src/fitmas/domain/planning/reference_resolver.py`
- Create: `tests/test_domain_planning_reference_resolver.py`

- [ ] **Step 1: Write resolver tests**

Create `tests/test_domain_planning_reference_resolver.py`:

```python
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.reference_resolver import ReferenceResolver


def _context(*sessions):
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso="2026-05-14"),
        plan=SimpleNamespace(scheduled_sessions=tuple(sessions)),
    )


def _session(session_id: int, scheduled_date: str):
    return SimpleNamespace(id=session_id, scheduled_date=scheduled_date, duration_min=45)


def test_resolver_resolves_session_id_and_date_refs() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="date:2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    resolved = ReferenceResolver(_context(_session(42, "2026-05-14"))).resolve(requested)

    assert resolved.source.kind == "session"
    assert resolved.source.session_id == 42
    assert resolved.target.kind == "date"
    assert resolved.target.date == date(2026, 5, 15)
    assert resolved.warnings == ()


def test_resolver_resolves_day_ref_against_current_week() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="day:friday",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    resolved = ReferenceResolver(_context(_session(42, "2026-05-14"))).resolve(requested)

    assert resolved.target.kind == "date"
    assert resolved.target.date == date(2026, 5, 15)


def test_resolver_does_not_guess_unknown_free_text_refs() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="la seance dure de ce soir",
        target_ref="vendredi",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    resolved = ReferenceResolver(_context(_session(42, "2026-05-14"))).resolve(requested)

    assert resolved.source.kind == "unknown"
    assert resolved.target.kind == "unknown"
    assert "unresolved_source_ref" in resolved.warnings
    assert "unresolved_target_ref" in resolved.warnings
```

- [ ] **Step 2: Run resolver tests and verify they fail**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_reference_resolver.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.domain.planning.reference_resolver'
```

- [ ] **Step 3: Implement resolver**

Create `backend/src/fitmas/domain/planning/reference_resolver.py`:

```python
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.models import PlanChangeReference, ResolvedPlanChange

_DAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


class ReferenceResolver:
    def __init__(self, context: Any):
        self._context = context

    def resolve(self, requested_change: RequestedPlanChange) -> ResolvedPlanChange:
        source = self._parse_ref(requested_change.source_ref)
        target = self._parse_ref(requested_change.target_ref)
        warnings = self._warnings(source=source, target=target)
        return ResolvedPlanChange(
            requested_change=requested_change,
            source=source,
            target=target,
            warnings=warnings,
        )

    def _parse_ref(self, raw_ref: str | None) -> PlanChangeReference:
        raw = str(raw_ref or "").strip()
        if not raw:
            return PlanChangeReference(kind="unknown", raw=raw_ref, session_id=None, date=None)
        if raw.startswith("session_id:"):
            return self._session_ref(raw)
        if raw.startswith("date:"):
            return self._date_ref(raw)
        if raw.startswith("day:"):
            return self._day_ref(raw)
        return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)

    def _session_ref(self, raw: str) -> PlanChangeReference:
        try:
            session_id = int(raw.split(":", 1)[1])
        except (TypeError, ValueError):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        if not any(_session_id(session) == session_id for session in _scheduled_sessions(self._context)):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=session_id, date=None)
        return PlanChangeReference(kind="session", raw=raw, session_id=session_id, date=None)

    def _date_ref(self, raw: str) -> PlanChangeReference:
        try:
            resolved_date = date.fromisoformat(raw.split(":", 1)[1][:10])
        except (IndexError, ValueError):
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        return PlanChangeReference(kind="date", raw=raw, session_id=None, date=resolved_date)

    def _day_ref(self, raw: str) -> PlanChangeReference:
        day_name = raw.split(":", 1)[1].strip().lower()
        if day_name not in _DAY_INDEX:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        today = _today(self._context)
        if today is None:
            return PlanChangeReference(kind="unknown", raw=raw, session_id=None, date=None)
        delta = (_DAY_INDEX[day_name] - today.weekday()) % 7
        return PlanChangeReference(kind="date", raw=raw, session_id=None, date=today + timedelta(days=delta))

    def _warnings(self, *, source: PlanChangeReference, target: PlanChangeReference) -> tuple[str, ...]:
        warnings: list[str] = []
        if source.raw and source.kind == "unknown":
            warnings.append("unresolved_source_ref")
        if target.raw and target.kind == "unknown":
            warnings.append("unresolved_target_ref")
        return tuple(warnings)


def _scheduled_sessions(context: Any) -> tuple[Any, ...]:
    return tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())


def _session_id(session: Any) -> int | None:
    raw = _value(session, "id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _today(context: Any) -> date | None:
    raw = getattr(getattr(context, "local_time", None), "today_iso", None)
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
```

- [ ] **Step 4: Run resolver tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_reference_resolver.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/domain/planning/reference_resolver.py tests/test_domain_planning_reference_resolver.py tests/test_decision_runtime_architecture.py
git commit -m "refactor: resolve typed planning references"
```

## Task 3: CandidateBuilder From ResolvedPlanChange

**Files:**
- Create: `backend/src/fitmas/domain/planning/candidate_builder.py`
- Create: `tests/test_domain_planning_candidate_builder.py`

- [ ] **Step 1: Write builder tests**

Create `tests/test_domain_planning_candidate_builder.py`:

```python
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.candidate_builder import PlanCandidateBuilder
from fitmas.domain.planning.models import PlanChangeReference, ResolvedPlanChange


def _session(session_id: int, scheduled_date: str = "2026-05-14", duration_min: int = 45):
    return SimpleNamespace(
        id=session_id,
        scheduled_date=scheduled_date,
        session_title="Tempo",
        sport_type="running",
        session_type="tempo",
        duration_min=duration_min,
        completion_status=None,
    )


def _context(*sessions):
    return SimpleNamespace(plan=SimpleNamespace(scheduled_sessions=tuple(sessions)))


def _resolved(kind: str, *, source_session_id: int | None, target_date: date | None):
    requested = RequestedPlanChange(
        kind=kind,
        source_ref=f"session_id:{source_session_id}" if source_session_id else None,
        target_ref=f"date:{target_date.isoformat()}" if target_date else None,
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=("fatigue",),
    )
    return ResolvedPlanChange(
        requested_change=requested,
        source=PlanChangeReference(kind="session" if source_session_id else "unknown", raw=requested.source_ref, session_id=source_session_id, date=None),
        target=PlanChangeReference(kind="date" if target_date else "unknown", raw=requested.target_ref, session_id=None, date=target_date),
        warnings=(),
    )


def test_builder_builds_move_candidate_from_resolved_refs() -> None:
    candidate_set = PlanCandidateBuilder(_context(_session(42))).build(
        _resolved("move", source_session_id=42, target_date=date(2026, 5, 15))
    )

    assert len(candidate_set.candidates) == 1
    candidate = candidate_set.candidates[0]
    assert candidate.candidate_ref == "backend:move_session:42:2026-05-15"
    patch = candidate_set.backend_candidate_patches[candidate.candidate_ref]
    assert patch.operations[0].operation_type == "move_session"
    assert patch.operations[0].target_session_id == 42
    assert patch.operations[0].target_date == "2026-05-15"


def test_builder_builds_lighten_candidate() -> None:
    candidate_set = PlanCandidateBuilder(_context(_session(42, duration_min=50))).build(
        _resolved("lighten", source_session_id=42, target_date=None)
    )

    patch = next(iter(candidate_set.backend_candidate_patches.values()))
    assert patch.operations[0].operation_type == "lighten_day"
    assert patch.operations[0].new_duration_min == 30
    assert patch.operations[0].new_intensity == "easy"


def test_builder_returns_empty_set_for_unresolved_source() -> None:
    candidate_set = PlanCandidateBuilder(_context(_session(42))).build(
        _resolved("move", source_session_id=None, target_date=date(2026, 5, 15))
    )

    assert candidate_set.candidates == ()
    assert candidate_set.backend_candidate_patches == {}
```

- [ ] **Step 2: Run builder tests and verify they fail**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_candidate_builder.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.domain.planning.candidate_builder'
```

- [ ] **Step 3: Implement builder**

Create `backend/src/fitmas/domain/planning/candidate_builder.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Any

from fitmas.domain.planning.models import PlanningCandidateSet, ResolvedPlanChange
from fitmas.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.plan_patch_candidates import PlanPatchCandidate

_PLAN_ID = "plan_current"
_PLAN_VERSION = 1


class PlanCandidateBuilder:
    def __init__(self, context: Any):
        self._context = context

    def build(self, resolved_change: ResolvedPlanChange) -> PlanningCandidateSet:
        patch = self._patch_for_change(resolved_change)
        if patch is None:
            return PlanningCandidateSet(candidates=(), backend_candidate_patches={})
        ref = _candidate_ref(resolved_change, patch)
        candidate = PlanPatchCandidate(
            id=ref,
            patches=(),
            rationale=resolved_change.reason or "Adaptation planning demandee.",
            expected_tradeoff="Option backend construite puis evaluee avant application.",
            confidence=0.85,
            assumptions=(),
            risk_notes=resolved_change.requested_change.risk_signals,
            created_from_plan_id=_PLAN_ID,
            created_from_plan_version=_PLAN_VERSION,
            candidate_ref=ref,
        )
        return PlanningCandidateSet(candidates=(candidate,), backend_candidate_patches={ref: patch})

    def _patch_for_change(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        kind = resolved_change.kind
        if kind == "move":
            return self._move_patch(resolved_change)
        if kind == "lighten":
            return self._lighten_patch(resolved_change)
        if kind == "replace":
            return self._replace_patch(resolved_change)
        if kind == "swap":
            return self._swap_patch(resolved_change)
        if kind == "create":
            return self._create_patch(resolved_change)
        return None

    def _move_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        session_id = resolved_change.source.session_id
        target_date = resolved_change.target.date
        if session_id is None or target_date is None:
            return None
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session_id,
                    target_date=target_date.isoformat(),
                    rationale=resolved_change.reason,
                )
            ],
            coach_message="Candidate backend, pas une reponse finale.",
        )

    def _lighten_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        session_id = resolved_change.source.session_id
        if session_id is None:
            return None
        duration = _light_duration(_session_by_id(self._context, session_id))
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="lighten_day",
                    target_session_id=session_id,
                    new_title="Seance allegee",
                    new_goal="Garder le geste sans accumuler de fatigue.",
                    new_duration_min=duration,
                    new_intensity="easy",
                    new_description="Version facile et raccourcie, sans chercher la performance.",
                    rationale=resolved_change.reason,
                )
            ],
            coach_message="Candidate backend, pas une reponse finale.",
        )

    def _replace_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        session_id = resolved_change.source.session_id
        if session_id is None:
            return None
        requested = resolved_change.requested_change
        duration = requested.desired_duration_min or _light_duration(_session_by_id(self._context, session_id))
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="replace_session",
                    target_session_id=session_id,
                    new_title="Seance remplacee",
                    new_goal="Adapter la charge sans perdre la continuite.",
                    new_sport_type=requested.desired_sport or "mobility",
                    new_session_type="recovery" if requested.desired_sport is None else "support",
                    new_duration_min=duration,
                    new_intensity=requested.desired_intensity or "easy",
                    new_description="Remplacement backend borne avant evaluation sportive.",
                    rationale=resolved_change.reason,
                )
            ],
            coach_message="Candidate backend, pas une reponse finale.",
        )

    def _swap_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        source_id = resolved_change.source.session_id
        target_id = resolved_change.target.session_id
        if source_id is None or target_id is None:
            return None
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="swap_sessions",
                    target_session_id=source_id,
                    second_session_id=target_id,
                    rationale=resolved_change.reason,
                )
            ],
            coach_message="Candidate backend, pas une reponse finale.",
        )

    def _create_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        target_date = resolved_change.target.date
        requested = resolved_change.requested_change
        if target_date is None or requested.desired_sport is None:
            return None
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="create_session",
                    target_date=target_date.isoformat(),
                    new_title="Seance ajoutee",
                    new_goal="Ajouter une seance bornee depuis une intention structuree.",
                    new_sport_type=requested.desired_sport,
                    new_session_type="easy",
                    new_duration_min=requested.desired_duration_min or 30,
                    new_intensity=requested.desired_intensity or "easy",
                    new_description="Seance creee depuis RequestedPlanChange, avant validation.",
                    rationale=resolved_change.reason,
                )
            ],
            coach_message="Candidate backend, pas une reponse finale.",
        )


def _candidate_ref(resolved_change: ResolvedPlanChange, patch: PlanPatch) -> str:
    operation = patch.operations[0]
    if operation.operation_type == "move_session":
        return f"backend:move_session:{operation.target_session_id}:{operation.target_date}"
    if operation.operation_type == "swap_sessions":
        return f"backend:swap_sessions:{operation.target_session_id}:{operation.second_session_id}"
    if operation.operation_type == "lighten_day":
        return f"backend:lighten_day:{operation.target_session_id}:easy_{operation.new_duration_min}"
    if operation.operation_type == "replace_session":
        return f"backend:replace_session:{operation.target_session_id}:{operation.new_sport_type}_{operation.new_duration_min}"
    if operation.operation_type == "create_session":
        return f"backend:create_session:{operation.target_date}:{operation.new_sport_type}_{operation.new_duration_min}"
    return f"backend:{resolved_change.kind}:unknown"


def _session_by_id(context: Any, session_id: int) -> Any | None:
    sessions = tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())
    return next((session for session in sessions if _value(session, "id") == session_id), None)


def _light_duration(session: Any | None) -> int:
    raw = _value(session, "duration_min") if session is not None else None
    try:
        duration = int(raw or 30)
    except (TypeError, ValueError):
        duration = 30
    return max(15, min(duration, 30))


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
```

- [ ] **Step 4: Run builder tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_candidate_builder.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/domain/planning/candidate_builder.py tests/test_domain_planning_candidate_builder.py
git commit -m "refactor: build planning candidates from requested changes"
```

## Task 4: Evaluation And Policy Facade

**Files:**
- Create: `backend/src/fitmas/domain/planning/evaluator.py`
- Create: `backend/src/fitmas/domain/planning/policy.py`
- Create: `tests/test_domain_planning_evaluator_policy.py`

- [ ] **Step 1: Write facade tests**

Create `tests/test_domain_planning_evaluator_policy.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.domain.planning.evaluator import PlanCandidateEvaluator
from fitmas.domain.planning.models import PlanningCandidateSet
from fitmas.domain.planning.policy import SportPolicy
from fitmas.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate
from fitmas.plan_patch_candidates import PlanPatchCandidate, PlanPatchCandidateValidation
from fitmas.week_coherence import WeekCoherenceScore


def _candidate() -> PlanPatchCandidate:
    return PlanPatchCandidate(
        id="candidate_a",
        patches=(),
        rationale="move",
        expected_tradeoff="low",
        confidence=0.9,
        assumptions=(),
        risk_notes=(),
        created_from_plan_id="plan_current",
        created_from_plan_version=1,
        candidate_ref="backend:move_session:42:2026-05-15",
    )


def test_evaluator_delegates_to_existing_candidate_evaluator(monkeypatch) -> None:
    calls = []

    def fake_evaluate(db, **kwargs):
        calls.append(kwargs)
        candidate = kwargs["candidate"]
        return EvaluatedPlanPatchCandidate(
            candidate=candidate,
            candidate_validation=PlanPatchCandidateValidation(
                status="valid",
                patch_count=0,
                operation_count=0,
                operation_results=(),
            ),
            patch=kwargs["backend_candidate_patches"][candidate.candidate_ref],
            patch_validation=None,
            week_context=None,
            facts=None,
            score=WeekCoherenceScore(
                total=90,
                recovery=90,
                goal_alignment=90,
                progression=90,
                adherence=90,
                readiness_fit=90,
                constraint_fit=90,
                risk=90,
            ),
            findings=(),
            score_delta=0,
            policy_hint="commit_safe",
            evaluation_summary="ok",
        )

    monkeypatch.setattr("fitmas.domain.planning.evaluator.evaluate_plan_patch_candidate", fake_evaluate)
    patch = PlanPatch(
        coach_message="Candidate backend.",
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=42,
                target_date="2026-05-15",
                rationale="move",
            )
        ],
    )
    candidate_set = PlanningCandidateSet(
        candidates=(_candidate(),),
        backend_candidate_patches={"backend:move_session:42:2026-05-15": patch},
    )

    evaluated = PlanCandidateEvaluator(db=object(), user=SimpleNamespace(id=1, timezone="Europe/Paris")).evaluate(
        candidate_set,
        scheduled_sessions=(),
        activities=(),
        active_facts=(),
        coach_state_bundle=None,
    )

    assert len(evaluated) == 1
    assert calls[0]["current_plan_id"] == "plan_current"
    assert calls[0]["current_plan_version"] == 1
    assert calls[0]["backend_candidate_patches"] == candidate_set.backend_candidate_patches


def test_policy_maps_existing_policy_result() -> None:
    decision = SportPolicy().decide(())

    assert decision.action == "block"
    assert decision.reason == "Aucune option d'adaptation valide."
```

- [ ] **Step 2: Run facade tests and verify they fail**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_evaluator_policy.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.domain.planning.evaluator'
```

- [ ] **Step 3: Implement evaluator facade**

Create `backend/src/fitmas/domain/planning/evaluator.py`:

```python
from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas.domain.planning.models import PlanningCandidateSet
from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate, evaluate_plan_patch_candidate
from fitmas.plan_patch_candidates import ALLOWED_CANDIDATE_OPERATION_TYPES


class PlanCandidateEvaluator:
    def __init__(self, *, db: Session, user: Any):
        self._db = db
        self._user = user

    def evaluate(
        self,
        candidate_set: PlanningCandidateSet,
        *,
        scheduled_sessions: Sequence[Any],
        activities: Sequence[Any],
        active_facts: Sequence[Any],
        coach_state_bundle: Any | None,
    ) -> tuple[EvaluatedPlanPatchCandidate, ...]:
        return tuple(
            evaluate_plan_patch_candidate(
                self._db,
                candidate=candidate,
                current_plan_id="plan_current",
                current_plan_version=1,
                plan_id=0,
                scheduled_sessions=scheduled_sessions,
                current_score=None,
                timezone_name=getattr(self._user, "timezone", None),
                allowed_operations=tuple(ALLOWED_CANDIDATE_OPERATION_TYPES),
                backend_candidate_patches=candidate_set.backend_candidate_patches,
                coach_state_bundle=coach_state_bundle,
                activities=activities,
                active_facts=active_facts,
            )
            for candidate in candidate_set.candidates
        )
```

- [ ] **Step 4: Implement policy facade**

Create `backend/src/fitmas/domain/planning/policy.py`:

```python
from __future__ import annotations

from typing import Sequence

from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision, decide_adaptation_policy
from fitmas.plan_patch_candidate_evaluator import EvaluatedPlanPatchCandidate
from fitmas.plan_patch_candidate_reviewer import PlanPatchCandidateReviewDecision


class SportPolicy:
    def decide(
        self,
        evaluated_candidates: Sequence[EvaluatedPlanPatchCandidate],
        *,
        reviewer_decision: PlanPatchCandidateReviewDecision | None = None,
    ) -> AdaptationPolicyDecision:
        return decide_adaptation_policy(evaluated_candidates, reviewer_decision=reviewer_decision)
```

- [ ] **Step 5: Run facade tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_evaluator_policy.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/domain/planning/evaluator.py backend/src/fitmas/domain/planning/policy.py tests/test_domain_planning_evaluator_policy.py
git commit -m "refactor: add planning evaluator policy facade"
```

## Task 5: PlanningCommandService As The New Writer

**Files:**
- Create: `backend/src/fitmas/domain/planning/mutation_service.py`
- Create: `tests/test_domain_planning_mutation_service.py`

- [ ] **Step 1: Write command service tests**

Create `tests/test_domain_planning_mutation_service.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.domain.planning.mutation_service import PlanningCommandService
from fitmas.plan_patch import PlanPatch, PlanPatchOperation, PlanPatchValidation
from fitmas.plan_patch_adaptation_policy import AdaptationPolicyDecision


def _patch() -> PlanPatch:
    return PlanPatch(
        coach_message="Candidate backend.",
        operations=[
            PlanPatchOperation(
                operation_type="move_session",
                target_session_id=42,
                target_date="2026-05-15",
                rationale="move",
            )
        ],
    )


def _decision(kind: str, *, patch: PlanPatch | None = None) -> PlanningDecisionResult:
    return PlanningDecisionResult(
        kind=kind,
        selected_candidate_id="candidate_a" if patch else None,
        candidate_options=(),
        reason="reason",
        policy_decision=AdaptationPolicyDecision(
            action=kind,
            selected_candidate_id="candidate_a" if patch else None,
            candidate_options=(),
            reason="reason",
            user_facing_reason="reason",
            requires_confirmation_reason="reason" if kind.startswith("pending") else None,
            risk_level="medium" if kind.startswith("pending") else "low",
        ),
        selected_patch=patch,
        evaluated_candidates=(),
        command_result=None,
        pending_confirmation_id=None,
    )


def test_command_service_commits_selected_patch(monkeypatch) -> None:
    calls = []

    def fake_apply_patch_for_user(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            mutation_result=SimpleNamespace(event_count=1),
            validation=PlanPatchValidation(status="valid", operation_results=(), summary="valid"),
        )

    monkeypatch.setattr("fitmas.domain.planning.mutation_service.apply_patch_for_user", fake_apply_patch_for_user)

    result = PlanningCommandService(db=object(), user=SimpleNamespace(id=1)).apply(
        _decision("commit", patch=_patch()),
        source_text="deplace",
        coach_state_bundle=None,
        activities=(),
        active_facts=(),
    )

    assert result.status == "applied"
    assert result.event_count == 1
    assert calls[0]["trigger_type"] == "planning_decision_runtime"


def test_command_service_persists_pending_confirmation(monkeypatch) -> None:
    pending_rows = []

    def fake_create_pending_mutation_confirmation(db, **kwargs):
        pending_rows.append(kwargs)
        return SimpleNamespace(id=99)

    monkeypatch.setattr("fitmas.domain.planning.mutation_service.repo.create_pending_mutation_confirmation", fake_create_pending_mutation_confirmation)

    result = PlanningCommandService(db=object(), user=SimpleNamespace(id=1)).apply(
        _decision("pending_confirmation", patch=_patch()),
        source_text="deplace",
        coach_state_bundle=None,
        activities=(),
        active_facts=(),
    )

    assert result.status == "pending"
    assert result.pending_confirmation_id == 99
    assert pending_rows[0]["mutation_type"] == "plan_patch"
```

- [ ] **Step 2: Run command service tests and verify they fail**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_mutation_service.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.domain.planning.mutation_service'
```

- [ ] **Step 3: Implement command service**

Create `backend/src/fitmas/domain/planning/mutation_service.py`:

```python
from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas import repository as repo
from fitmas.domain.planning.models import PlanningCommandResult, PlanningDecisionResult
from fitmas.mutation_permissions import (
    default_confirmation_expiry,
    serialize_plan_patch_choice_confirmation,
    serialize_plan_patch_confirmation,
)
from fitmas.plan_mutation_service import apply_patch_for_user


class PlanningCommandService:
    def __init__(self, *, db: Session, user: Any):
        self._db = db
        self._user = user

    def apply(
        self,
        decision: PlanningDecisionResult,
        *,
        source_text: str,
        coach_state_bundle: Any | None,
        activities: Sequence[Any],
        active_facts: Sequence[Any],
    ) -> PlanningCommandResult:
        if decision.kind == "commit":
            return self._commit(
                decision,
                coach_state_bundle=coach_state_bundle,
                activities=activities,
                active_facts=active_facts,
            )
        if decision.kind == "pending_confirmation":
            return self._pending_confirmation(decision, source_text=source_text)
        if decision.kind == "pending_choice":
            return self._pending_choice(decision, source_text=source_text)
        return PlanningCommandResult(
            status="blocked",
            event_count=0,
            pending_confirmation_id=None,
            service_result=None,
            payload={"reason": decision.reason},
        )

    def _commit(
        self,
        decision: PlanningDecisionResult,
        *,
        coach_state_bundle: Any | None,
        activities: Sequence[Any],
        active_facts: Sequence[Any],
    ) -> PlanningCommandResult:
        if decision.selected_patch is None:
            return PlanningCommandResult(
                status="blocked",
                event_count=0,
                pending_confirmation_id=None,
                service_result=None,
                payload={"reason": "missing_selected_patch"},
            )
        service_result = apply_patch_for_user(
            self._db,
            user=self._user,
            patch=decision.selected_patch,
            source="conversation",
            trigger_type="planning_decision_runtime",
            explained_to_user=True,
            coach_state_bundle=coach_state_bundle,
            activities=activities,
            active_facts=active_facts,
        )
        event_count = int(getattr(getattr(service_result, "mutation_result", None), "event_count", 0) or 0)
        return PlanningCommandResult(
            status="applied" if event_count > 0 else "blocked",
            event_count=event_count,
            pending_confirmation_id=None,
            service_result=service_result,
            payload={"selected_candidate_id": decision.selected_candidate_id},
        )

    def _pending_confirmation(self, decision: PlanningDecisionResult, *, source_text: str) -> PlanningCommandResult:
        if decision.selected_patch is None:
            return PlanningCommandResult(
                status="blocked",
                event_count=0,
                pending_confirmation_id=None,
                service_result=None,
                payload={"reason": "missing_selected_patch"},
            )
        row = repo.create_pending_mutation_confirmation(
            self._db,
            user_id=self._user.id,
            impact_level="high",
            reason=decision.reason,
            mutation_type="plan_patch",
            summary=decision.reason,
            source_text=source_text,
            decision_json=serialize_plan_patch_confirmation(decision.selected_patch),
            expires_at=default_confirmation_expiry(),
        )
        return PlanningCommandResult(
            status="pending",
            event_count=0,
            pending_confirmation_id=row.id,
            service_result=None,
            payload={"selected_candidate_id": decision.selected_candidate_id},
        )

    def _pending_choice(self, decision: PlanningDecisionResult, *, source_text: str) -> PlanningCommandResult:
        choice_candidates = tuple(
            evaluated.candidate
            for evaluated in decision.evaluated_candidates
            if evaluated.candidate.id in set(decision.candidate_options)
        )
        row = repo.create_pending_mutation_confirmation(
            self._db,
            user_id=self._user.id,
            impact_level="medium",
            reason=decision.reason,
            mutation_type="plan_patch_choice",
            summary=decision.reason,
            source_text=source_text,
            decision_json=serialize_plan_patch_choice_confirmation(choice_candidates),
            expires_at=default_confirmation_expiry(),
        )
        return PlanningCommandResult(
            status="pending",
            event_count=0,
            pending_confirmation_id=row.id,
            service_result=None,
            payload={"candidate_options": decision.candidate_options},
        )
```

- [ ] **Step 4: Run command service tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_mutation_service.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/domain/planning/mutation_service.py tests/test_domain_planning_mutation_service.py
git commit -m "refactor: add planning command service"
```

## Task 6: Decision Service Entry Point

**Files:**
- Create: `backend/src/fitmas/domain/planning/decision_service.py`
- Modify: `backend/src/fitmas/domain/planning/__init__.py`
- Create: `tests/test_domain_planning_decision_service.py`

- [ ] **Step 1: Write decision service tests**

Create `tests/test_domain_planning_decision_service.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.decision_service import decide_plan_change


def _context():
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso="2026-05-14"),
        plan=SimpleNamespace(
            scheduled_sessions=(
                SimpleNamespace(id=42, scheduled_date="2026-05-14", duration_min=45, completion_status=None),
            )
        ),
        execution=SimpleNamespace(activities=()),
        memory=SimpleNamespace(active_facts=()),
    )


def test_decide_plan_change_blocks_unresolved_change() -> None:
    requested = RequestedPlanChange(
        kind="move",
        source_ref="seance dure",
        target_ref="vendredi",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    result = decide_plan_change(
        requested,
        context=_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result.kind == "block"
    assert "unresolved" in result.reason


def test_decide_plan_change_builds_and_policies_resolved_change(monkeypatch) -> None:
    calls = []

    class FakeEvaluator:
        def __init__(self, *, db, user):
            pass

        def evaluate(self, candidate_set, **kwargs):
            calls.append(candidate_set)
            return ()

    monkeypatch.setattr("fitmas.domain.planning.decision_service.PlanCandidateEvaluator", FakeEvaluator)

    requested = RequestedPlanChange(
        kind="move",
        source_ref="session_id:42",
        target_ref="date:2026-05-15",
        desired_sport=None,
        desired_duration_min=None,
        desired_intensity=None,
        reason="fatigue",
        risk_signals=(),
    )

    result = decide_plan_change(
        requested,
        context=_context(),
        db=object(),
        user=SimpleNamespace(id=1, timezone="Europe/Paris"),
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert calls
    assert result.kind == "block"
    assert result.reason == "Aucune option d'adaptation valide."
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_decision_service.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.domain.planning.decision_service'
```

- [ ] **Step 3: Implement decision service**

Create `backend/src/fitmas/domain/planning/decision_service.py`:

```python
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from fitmas.decision import RequestedPlanChange
from fitmas.domain.planning.candidate_builder import PlanCandidateBuilder
from fitmas.domain.planning.evaluator import PlanCandidateEvaluator
from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.domain.planning.policy import SportPolicy
from fitmas.domain.planning.reference_resolver import ReferenceResolver
from fitmas.plan_patch_candidate_reviewer import review_plan_patch_candidates


def decide_plan_change(
    requested_change: RequestedPlanChange,
    *,
    context: Any,
    db: Session,
    user: Any,
    coach_state_bundle: Any | None,
    reviewer_request_json_fn,
) -> PlanningDecisionResult:
    resolved = ReferenceResolver(context).resolve(requested_change)
    if any(item.startswith("unresolved") for item in resolved.warnings):
        return PlanningDecisionResult(
            kind="block",
            selected_candidate_id=None,
            candidate_options=(),
            reason=", ".join(resolved.warnings),
            policy_decision=None,
            selected_patch=None,
            evaluated_candidates=(),
            command_result=None,
            pending_confirmation_id=None,
        )
    candidate_set = PlanCandidateBuilder(context).build(resolved)
    evaluated = PlanCandidateEvaluator(db=db, user=user).evaluate(
        candidate_set,
        scheduled_sessions=tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ()),
        activities=tuple(getattr(getattr(context, "execution", None), "activities", ()) or ()),
        active_facts=tuple(getattr(getattr(context, "memory", None), "active_facts", ()) or ()),
        coach_state_bundle=coach_state_bundle,
    )
    reviewer_decision = None
    if reviewer_request_json_fn is not None:
        reviewer_decision = review_plan_patch_candidates(evaluated, request_json_fn=reviewer_request_json_fn)
    policy_decision = SportPolicy().decide(evaluated, reviewer_decision=reviewer_decision)
    selected = _selected_evaluated(policy_decision.selected_candidate_id, evaluated)
    selected_patch = selected.patch if selected is not None else None
    return PlanningDecisionResult(
        kind=policy_decision.action,
        selected_candidate_id=policy_decision.selected_candidate_id,
        candidate_options=policy_decision.candidate_options,
        reason=policy_decision.requires_confirmation_reason or policy_decision.reason,
        policy_decision=policy_decision,
        selected_patch=selected_patch,
        evaluated_candidates=tuple(evaluated),
        command_result=None,
        pending_confirmation_id=None,
    )


def _selected_evaluated(selected_candidate_id: str | None, evaluated) -> Any | None:
    if selected_candidate_id is None:
        return None
    return next((candidate for candidate in evaluated if candidate.candidate.id == selected_candidate_id), None)
```

- [ ] **Step 4: Export decision service**

Modify `backend/src/fitmas/domain/planning/__init__.py`:

```python
from .decision_service import decide_plan_change
from .models import (
    PlanChangeReference,
    PlanningCandidateSet,
    PlanningCommandResult,
    PlanningDecisionResult,
    ResolvedPlanChange,
)

__all__ = [
    "PlanChangeReference",
    "PlanningCandidateSet",
    "PlanningCommandResult",
    "PlanningDecisionResult",
    "ResolvedPlanChange",
    "decide_plan_change",
]
```

- [ ] **Step 5: Run decision service tests**

Run:

```bash
./scripts/test-backend tests/test_domain_planning_decision_service.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/domain/planning/decision_service.py backend/src/fitmas/domain/planning/__init__.py tests/test_domain_planning_decision_service.py
git commit -m "refactor: add planning decision service"
```

## Task 7: Conversation Adapter Cutover

**Files:**
- Create: `backend/src/fitmas/legacy/planning_runtime_adapter.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Create: `tests/test_conversation_planning_runtime_adapter.py`

This task replaces the direct planning path for `CoachDecision` planning outputs with one adapter call. It does not touch memory/execution action application.

- [ ] **Step 1: Write adapter tests**

Create `tests/test_conversation_planning_runtime_adapter.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy.planning_runtime_adapter import maybe_run_planning_runtime_from_legacy_decision
from fitmas.llm import CoachDecision
from fitmas.plan_patch import PlanPatch, PlanPatchOperation


def test_adapter_returns_none_for_non_planning_decision() -> None:
    decision = CoachDecision(
        response_type="no_change",
        rationale="lecture",
        fitmas_message="Message legacy.",
    )

    result = maybe_run_planning_runtime_from_legacy_decision(
        decision=decision,
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="ok",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert result is None


def test_adapter_runs_decision_service_for_requested_change(monkeypatch) -> None:
    calls = []

    def fake_decide_plan_change(requested_change, **kwargs):
        calls.append(requested_change)
        return SimpleNamespace(
            kind="block",
            reason="Aucune option valide.",
            command_result=None,
            pending_confirmation_id=None,
        )

    monkeypatch.setattr("fitmas.legacy.planning_runtime_adapter.decide_plan_change", fake_decide_plan_change)

    decision = CoachDecision(
        response_type="plan_patch",
        rationale="deplacement",
        fitmas_message="Message legacy.",
        plan_patch=PlanPatch(
            coach_message="patch",
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=42,
                    target_date="2026-05-15",
                    rationale="move",
                )
            ],
        ),
    )

    result = maybe_run_planning_runtime_from_legacy_decision(
        decision=decision,
        context=SimpleNamespace(),
        db=object(),
        user=SimpleNamespace(id=1),
        source_text="deplace",
        coach_state_bundle=None,
        reviewer_request_json_fn=None,
    )

    assert calls
    assert result is not None
    assert result.kind == "block"
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```bash
./scripts/test-backend tests/test_conversation_planning_runtime_adapter.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.legacy.planning_runtime_adapter'
```

- [ ] **Step 3: Implement adapter**

Create `backend/src/fitmas/legacy/planning_runtime_adapter.py`:

```python
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from fitmas.domain.planning.decision_service import decide_plan_change
from fitmas.domain.planning.models import PlanningDecisionResult
from fitmas.domain.planning.mutation_service import PlanningCommandService
from fitmas.legacy.coach_understanding_adapter import coach_decision_to_understanding


def maybe_run_planning_runtime_from_legacy_decision(
    *,
    decision: Any,
    context: Any,
    db: Session,
    user: Any,
    source_text: str,
    coach_state_bundle: Any | None,
    reviewer_request_json_fn,
) -> PlanningDecisionResult | None:
    understanding = coach_decision_to_understanding(decision)
    if understanding.requested_change is None:
        return None
    planning_decision = decide_plan_change(
        understanding.requested_change,
        context=context,
        db=db,
        user=user,
        coach_state_bundle=coach_state_bundle,
        reviewer_request_json_fn=reviewer_request_json_fn,
    )
    command_result = PlanningCommandService(db=db, user=user).apply(
        planning_decision,
        source_text=source_text,
        coach_state_bundle=coach_state_bundle,
        activities=tuple(getattr(getattr(context, "execution", None), "activities", ()) or ()),
        active_facts=tuple(getattr(getattr(context, "memory", None), "active_facts", ()) or ()),
    )
    return PlanningDecisionResult(
        kind=planning_decision.kind,
        selected_candidate_id=planning_decision.selected_candidate_id,
        candidate_options=planning_decision.candidate_options,
        reason=planning_decision.reason,
        policy_decision=planning_decision.policy_decision,
        selected_patch=planning_decision.selected_patch,
        evaluated_candidates=planning_decision.evaluated_candidates,
        command_result=command_result,
        pending_confirmation_id=command_result.pending_confirmation_id,
    )
```

- [ ] **Step 4: Run adapter tests**

Run:

```bash
./scripts/test-backend tests/test_conversation_planning_runtime_adapter.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Wire one conversation call**

Modify `backend/src/fitmas/conversation_pipeline.py`.

Add import:

```python
from fitmas.legacy.planning_runtime_adapter import maybe_run_planning_runtime_from_legacy_decision
```

Inside the `_is_coach_decision(decision)` block, after `_apply_pending_resolution(...)` and before `_should_try_mixed_plan_adaptation_after_decide(...)`, add a single call:

```python
        if outcome is None and decision is not None:
            planning_context = _planning_context_from_turn_state(
                user=user,
                state=state,
                conversation_context=conversation_context,
                coach_bundle=coach_bundle,
            )
            planning_runtime_result = maybe_run_planning_runtime_from_legacy_decision(
                decision=decision,
                context=planning_context,
                db=db,
                user=user,
                source_text=payload.text,
                coach_state_bundle=coach_bundle,
                reviewer_request_json_fn=gw.request_json,
            )
            if planning_runtime_result is not None:
                outcome = _conversation_outcome_from_planning_runtime_result(
                    planning_runtime_result,
                    user_text=payload.text,
                    scheduled_sessions=state.scheduled_sessions,
                    grounding=grounding_packet,
                )
                decision = None
```

Create a private helper that builds the minimal shape consumed by Phase 4:

```python
def _planning_context_from_turn_state(*, user, state, conversation_context, coach_bundle):
    return SimpleNamespace(
        local_time=SimpleNamespace(today_iso=conversation_context.temporal_resolution.local_date.isoformat()),
        plan=SimpleNamespace(scheduled_sessions=tuple(state.scheduled_sessions)),
        execution=SimpleNamespace(activities=tuple(state.activities)),
        memory=SimpleNamespace(active_facts=tuple(state.active_facts)),
        weekly_digest=SimpleNamespace(coach_reading=coach_bundle.coach_reading),
    )
```

Use the minimal helper only in this legacy adapter slice. Phase 5+ can remove it when the whole conversation pipeline becomes `DecisionRuntime`.

- [ ] **Step 6: Add outcome mapper**

In `backend/src/fitmas/conversation_pipeline.py`, add:

```python
def _conversation_outcome_from_planning_runtime_result(
    result,
    *,
    user_text: str,
    scheduled_sessions: list[Any],
    grounding: ReplyGroundingPacket | None,
) -> ConversationTurnOutcome:
    if result.kind == "commit" and result.command_result is not None and result.command_result.status == "applied":
        service_result = result.command_result.service_result
        reply_text = _applied_plan_patch_reply(service_result, fallback="J'ai applique l'adaptation.")
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=reply_text,
            response_mode="planning_runtime_commit",
            mutation_applied=True,
        )
    if result.kind in {"pending_confirmation", "pending_choice"}:
        return ConversationTurnOutcome(
            extraction=Extraction(confidence=0.85),
            reply_text=result.reason,
            response_mode=f"planning_runtime_{result.kind}",
            mutation_applied=False,
            pending_confirmation=True,
            pending_confirmation_id=result.pending_confirmation_id,
        )
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=result.reason,
        response_mode="planning_runtime_block",
        mutation_applied=False,
    )
```

This mapper is temporary. Phase 5 replaces it with `ReplyComposer`.

- [ ] **Step 7: Run conversation adapter tests**

Run:

```bash
./scripts/test-backend tests/test_conversation_planning_runtime_adapter.py tests/test_core_flows.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 8: Commit**

```bash
git add backend/src/fitmas/legacy/planning_runtime_adapter.py backend/src/fitmas/conversation_pipeline.py tests/test_conversation_planning_runtime_adapter.py
git commit -m "refactor: route legacy planning through planning runtime"
```

## Task 8: Tighten Architecture Tests After Cutover

**Files:**
- Modify: `tests/test_decision_runtime_architecture.py`
- Create: `tests/test_phase4_planning_architecture.py`

- [ ] **Step 1: Write Phase 4 architecture tests**

Create `tests/test_phase4_planning_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FITMAS = ROOT / "backend" / "src" / "fitmas"
PLANNING = FITMAS / "domain" / "planning"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_reference_resolver_does_not_import_llm_or_tools() -> None:
    imports = _imports(PLANNING / "reference_resolver.py")
    forbidden = {"fitmas.llm", "fitmas.tools", "fitmas.tools.registry"}

    assert imports.isdisjoint(forbidden)


def test_candidate_builder_never_writes() -> None:
    source = (PLANNING / "candidate_builder.py").read_text(encoding="utf-8")
    forbidden = (".add(", ".commit(", ".flush(", "apply_patch_for_user", "create_pending_mutation_confirmation")

    assert [token for token in forbidden if token in source] == []


def test_new_planning_writes_are_confined_to_planning_command_service() -> None:
    offenders: list[str] = []
    for path in sorted(PLANNING.glob("*.py")):
        if path.name == "mutation_service.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "apply_patch_for_user" in source or "create_pending_mutation_confirmation" in source:
            offenders.append(path.name)

    assert offenders == []
```

- [ ] **Step 2: Run architecture tests**

Run:

```bash
./scripts/test-backend tests/test_phase4_planning_architecture.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_phase4_planning_architecture.py tests/test_decision_runtime_architecture.py
git commit -m "test: guard planning runtime boundaries"
```

## Task 9: Documentation And Verification

**Files:**
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] **Step 1: Update canonical refactor doc**

In `docs/DECISION-RUNTIME-REFACTOR.md`, add:

```markdown
Livres en Phase 4 initiale :

- `backend/src/fitmas/domain/planning/` cree comme bounded context cible ;
- `ReferenceResolver` resout uniquement des refs typees, jamais le texte user ;
- `PlanCandidateBuilder` construit les candidates backend depuis `RequestedPlanChange` ;
- evaluator/reviewer/policy existants sont reutilises derriere des facades domaine ;
- `PlanningCommandService` devient le writer Phase 4 pour commit et pending ;
- `conversation_pipeline.py` appelle un seul adapter planning runtime avant les branches legacy ;
- `PlanPatch` reste langage interne backend, pas sortie d'autorite du LLM.
```

- [ ] **Step 2: Update build order**

In `docs/BUILD-ORDER.md`, update active status:

```markdown
- Phase 4 initiale livree localement :
  - planning domain package cree ;
  - RequestedPlanChange passe par resolver -> candidates -> evaluator -> policy ;
  - writes Phase 4 concentres dans PlanningCommandService ;
  - l'ancien code flat reste compat interne jusqu'a la phase kill legacy.
```

- [ ] **Step 3: Run targeted tests**

Run:

```bash
./scripts/test-backend \
  tests/test_domain_planning_models.py \
  tests/test_domain_planning_reference_resolver.py \
  tests/test_domain_planning_candidate_builder.py \
  tests/test_domain_planning_evaluator_policy.py \
  tests/test_domain_planning_mutation_service.py \
  tests/test_domain_planning_decision_service.py \
  tests/test_conversation_planning_runtime_adapter.py \
  tests/test_phase4_planning_architecture.py \
  tests/test_decision_runtime_architecture.py \
  -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 4: Run legacy-sensitive tests**

Run:

```bash
./scripts/test-backend tests/test_core_flows.py tests/test_conversation_candidate_refs.py tests/test_plan_mutation_service.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Run full suite**

Run:

```bash
./scripts/test-backend -q
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
The Phase 4 plan appears with summary and read_when hints.
```

- [ ] **Step 7: Commit docs**

```bash
git add docs/DECISION-RUNTIME-REFACTOR.md docs/BUILD-ORDER.md docs/superpowers/plans/2026-05-14-decision-runtime-phase-4-planning-pipeline.md
git commit -m "docs: plan decision runtime phase 4"
```

## Acceptance Criteria

Phase 4 is complete when:

- new code path starts from `RequestedPlanChange`;
- reference resolution never reads free user text;
- backend candidates are constructed in `domain/planning/candidate_builder.py`;
- evaluator/reviewer/policy are called from `domain/planning`;
- new planning writes go through `PlanningCommandService`;
- conversation has one adapter call, not multiple new planning branches;
- existing direct `CoachDecision.plan_patch` behavior is covered by tests through the new adapter;
- full test suite passes;
- docs mark old flat planning modules as compatibility internals, not target architecture.

## What This Leaves For Phase 5

Phase 4 still uses existing final reply helpers to speak.

Phase 5 should replace that with:

```text
PlanningDecisionResult / DecisionOutcome
-> ReplyComposer
-> OutputVerifier
```

Do not start Phase 5 during Phase 4 unless Loic explicitly asks.
