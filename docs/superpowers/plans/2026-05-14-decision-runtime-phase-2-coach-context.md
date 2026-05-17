---
summary: implementation plan for Decision Runtime Phase 2 CoachContext canonical builder
read_when:
  - implementing Decision Runtime Phase 2
  - creating CoachContext or ContextBuilder
  - refactoring context passed to conversation, heartbeat or app
  - enforcing decision runtime boundaries after Phase 0/1
---

# Decision Runtime Phase 2 CoachContext Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the canonical `CoachContext` and a read-only `DecisionContextBuilder` from existing FitMAS truth sources without changing runtime behavior.

**Architecture:** Phase 2 keeps the new `decision/` package as the orchestration layer. `decision/context.py` owns pure typed context dataclasses. `decision/context_builder.py` is the only Phase 2 file in `decision/` allowed to read DB/repository state, and it folds existing `CoachStateBundle` truth into a canonical `CoachContext`. Nothing is wired into `conversation_pipeline.py`, heartbeat, app routes, prompts, writers or tools yet.

**Tech Stack:** Python 3.13, dataclasses, SQLAlchemy read-only Session in the builder only, pytest, existing `CoachStateBundle`, `ScheduledSession`, `Activity`, memory and readiness helpers.

---

## Phase 2 Boundary

This phase is not a behavior migration.

Allowed:

- strengthen `CoachContext` types;
- create `DecisionContextBuilder`;
- read DB state in `decision/context_builder.py` only;
- reuse `build_coach_state_bundle`;
- add architecture tests and builder tests;
- update docs after tests pass.

Forbidden:

- importing or editing `conversation_pipeline.py`;
- branching heartbeat or app through `DecisionRuntime`;
- adding prompts;
- calling LLMs;
- adding writers;
- importing `PlanPatch` or `MutationDecision`;
- reading `WeeklyPlan` / `DayPlan` as runtime truth;
- adding local guards or fallbacks.

The outcome is a context artifact ready for later phases, not a live path.

## Files

- Modify: `backend/src/fitmas/decision/context.py`
  - Replace the current `Any`-only `CoachContext` with focused dataclasses for local time, plan, execution, memory, athlete, readiness, load, weekly digest and pending state.
- Create: `backend/src/fitmas/decision/context_builder.py`
  - Owns read-only construction of `CoachContext` from `InputEvent + DB`.
- Modify: `backend/src/fitmas/decision/__init__.py`
  - Export the new pure context types only. Do not export the DB-backed builder
    from the root package.
- Modify: `tests/test_decision_types.py`
  - Assert the richer `CoachContext` can be constructed and remains free of reply/patch/write fields.
- Modify: `tests/test_decision_runtime_architecture.py`
  - Allow DB/repository imports only in `context_builder.py`; keep all pure decision modules DB-free.
- Create: `tests/test_decision_context_builder.py`
  - Integration-style unit tests for the read-only builder using the local test DB.
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
  - Add Phase 2 implementation status after code lands.
- Modify: `docs/BUILD-ORDER.md`
  - Mark Phase 2 local status after verification.

## Invariants

Copy these into every agent prompt for this phase:

```text
INVARIANTS FITMAS DECISION RUNTIME - PHASE 2

1. Phase 2 does not change runtime behavior.
2. `decision/context.py` remains pure dataclasses: no DB, no SQLAlchemy, no repository, no schema imports.
3. `decision/context_builder.py` is read-only orchestration. It may read DB state; it may not write.
4. `decision/context_builder.py` must not import conversation_pipeline, heartbeat, final_reply, llm, tools, PlanPatch or MutationDecision.
5. `CoachContext` must be built from ScheduledSession / Activity / Memory / Events truth, never DayPlan as runtime truth.
6. WeeklyPlan / DayPlan may remain in old modules, but Phase 2 must not create a new runtime dependency on them.
7. No prompt, LLM call, reply text, guard, fallback or command execution is introduced.
8. No API, Telegram, heartbeat or app route is rewired to the builder in this phase.
```

## Task 1: Tighten Architecture Tests for Phase 2

**Files:**
- Modify: `tests/test_decision_runtime_architecture.py`

- [ ] **Step 1: Write the failing test for pure decision modules**

Replace the current broad DB import test with a pure-module scoped version:

```python
PURE_DECISION_MODULES = {
    "__init__.py",
    "command_bus.py",
    "context.py",
    "explanation.py",
    "input_event.py",
    "outcome.py",
    "output_verifier.py",
    "reply_composer.py",
    "runtime.py",
    "understanding.py",
}


def test_pure_decision_modules_have_no_database_or_legacy_imports() -> None:
    forbidden_exact = {
        "sqlalchemy",
        "fitmas.db",
        "fitmas.repository",
        "fitmas.schema",
        "fitmas.models",
        "fitmas.legacy",
    }
    forbidden_prefixes = ("sqlalchemy.", "fitmas.legacy.")

    offenders: list[str] = []
    for path in _python_files():
        if path.name not in PURE_DECISION_MODULES:
            continue
        for module in _imports(path):
            if module in forbidden_exact or module.startswith(forbidden_prefixes):
                offenders.append(f"{path.name}: {module}")

    assert offenders == []
```

- [ ] **Step 2: Add the context_builder import boundary test**

Add:

```python
def test_context_builder_is_the_only_decision_module_allowed_to_read_repository() -> None:
    builder = DECISION / "context_builder.py"
    assert builder.exists()

    allowed = {
        "sqlalchemy.orm",
        "fitmas.repository",
        "fitmas.schema",
        "fitmas.coach_state_bundle",
        "fitmas.time_context",
    }
    imports = _imports(builder)
    read_imports = {module for module in imports if module in allowed}

    assert read_imports
    assert all(module in allowed or not module.startswith(("sqlalchemy", "fitmas.repository", "fitmas.schema")) for module in imports)
```

- [ ] **Step 3: Add no-write/no-runtime-branch test for context_builder**

Add:

```python
def test_context_builder_is_read_only_and_not_runtime_wired() -> None:
    source = (DECISION / "context_builder.py").read_text(encoding="utf-8")
    forbidden = (
        ".add(",
        ".delete(",
        ".commit(",
        ".flush(",
        "PlanMutationService",
        "MemoryMutationService",
        "ExecutionCommandService",
        "conversation_pipeline",
        "final_reply",
        "fitmas.llm",
        "fitmas.tools",
        "PlanPatch",
        "MutationDecision",
        "WeeklyPlan",
        "DayPlan",
        "get_active_plan",
        "to_pydantic_plan",
    )

    offenders = [token for token in forbidden if token in source]

    assert offenders == []
```

- [ ] **Step 4: Add no integration test for runtime files**

Add:

```python
def test_phase2_does_not_wire_existing_runtime_to_context_builder() -> None:
    root = ROOT / "backend" / "src" / "fitmas"
    files = [
        root / "conversation_pipeline.py",
        root / "skills" / "heartbeat" / "heartbeat.py",
        root / "api_app.py",
        root / "api_messages.py",
    ]
    offenders: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        if "DecisionContextBuilder" in source or "fitmas.decision.context_builder" in source:
            offenders.append(path.name)

    assert offenders == []
```

- [ ] **Step 5: Run the test and verify RED**

Run:

```bash
./scripts/test-backend tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
FAIL because backend/src/fitmas/decision/context_builder.py does not exist yet.
```

Do not implement before seeing this failure.

## Task 2: Define Canonical Context Types

**Files:**
- Modify: `backend/src/fitmas/decision/context.py`
- Modify: `tests/test_decision_types.py`

- [ ] **Step 1: Write the failing test for typed CoachContext**

Add to `tests/test_decision_types.py`:

```python
from fitmas.decision import (
    AthleteContext,
    ExecutionReality,
    LoadContext,
    LocalTimeContext,
    MemoryContext,
    PendingContext,
    PlanTimeline,
    ReadinessContext,
    WeeklyRealityDigest,
)


def test_coach_context_groups_truth_by_domain_without_reply_or_patch_fields() -> None:
    local_time = LocalTimeContext(
        timezone_name="Europe/Paris",
        now_iso="2026-05-14T08:30+02:00",
        today_iso="2026-05-14",
        time_context={"day_label_fr": "jeudi"},
    )
    plan = PlanTimeline(
        scheduled_sessions=("session-1",),
        session_policies=("policy-1",),
        planning_contract="contract",
        week_mission="mission",
        latest_adaptation=None,
        recent_adaptations=(),
    )
    execution = ExecutionReality(
        activities=("activity-1",),
        recent_reality="recent",
        today_execution=None,
    )
    memory = MemoryContext(active_memory=("profile",), active_facts=())
    athlete = AthleteContext(profile_snapshot="profile", calibration_status="calibration")
    readiness = ReadinessContext(snapshot=None, state=None)
    load = LoadContext(summary=None, forecast=None)
    weekly_digest = WeeklyRealityDigest(
        week_summary={"total_sessions": 1},
        planning_context={"mode": "maintain_load"},
        next_week={"focus": "stability"},
        coach_reading="Semaine stable.",
    )
    pending = PendingContext(active_pending=None, summary=None)

    context = CoachContext(
        user="user",
        local_time=local_time,
        plan=plan,
        execution=execution,
        memory=memory,
        athlete=athlete,
        readiness=readiness,
        load=load,
        weekly_digest=weekly_digest,
        pending=pending,
    )

    forbidden = {"fitmas_message", "reply_text", "plan_patch", "mutation_decision", "commands"}

    assert context.plan.scheduled_sessions == ("session-1",)
    assert context.weekly_digest.week_summary["total_sessions"] == 1
    assert _field_names(CoachContext).isdisjoint(forbidden)
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
./scripts/test-backend tests/test_decision_types.py::test_coach_context_groups_truth_by_domain_without_reply_or_patch_fields -q
```

Expected:

```text
FAIL because LocalTimeContext / PlanTimeline / ExecutionReality / MemoryContext / AthleteContext / ReadinessContext / LoadContext / WeeklyRealityDigest / PendingContext are not exported yet.
```

- [ ] **Step 3: Implement the minimal context dataclasses**

Replace `backend/src/fitmas/decision/context.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class LocalTimeContext:
    timezone_name: str
    now_iso: str
    today_iso: str
    time_context: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PlanTimeline:
    scheduled_sessions: tuple[Any, ...]
    session_policies: tuple[Any, ...]
    planning_contract: Any | None
    week_mission: Any | None
    latest_adaptation: Any | None
    recent_adaptations: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class ExecutionReality:
    activities: tuple[Any, ...]
    recent_reality: Any | None
    today_execution: Any | None


@dataclass(frozen=True, slots=True)
class MemoryContext:
    active_memory: tuple[Any, ...]
    active_facts: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class AthleteContext:
    profile_snapshot: Any | None
    calibration_status: Any | None


@dataclass(frozen=True, slots=True)
class ReadinessContext:
    snapshot: Any | None
    state: Any | None


@dataclass(frozen=True, slots=True)
class LoadContext:
    summary: Mapping[str, Any] | None
    forecast: Any | None


@dataclass(frozen=True, slots=True)
class WeeklyRealityDigest:
    week_summary: Mapping[str, Any]
    planning_context: Mapping[str, Any]
    next_week: Mapping[str, Any]
    coach_reading: str


@dataclass(frozen=True, slots=True)
class PendingContext:
    active_pending: Any | None
    summary: str | None


@dataclass(frozen=True, slots=True)
class CoachContext:
    user: Any
    local_time: LocalTimeContext
    plan: PlanTimeline
    execution: ExecutionReality
    memory: MemoryContext
    athlete: AthleteContext
    readiness: ReadinessContext
    load: LoadContext
    weekly_digest: WeeklyRealityDigest
    pending: PendingContext
```

- [ ] **Step 4: Export the new types**

Modify `backend/src/fitmas/decision/__init__.py` to import/export:

```python
from .context import (
    AthleteContext,
    CoachContext,
    ExecutionReality,
    LoadContext,
    LocalTimeContext,
    MemoryContext,
    PendingContext,
    PlanTimeline,
    ReadinessContext,
    WeeklyRealityDigest,
)
```

Add all names to `__all__`.

- [ ] **Step 5: Run the test and verify GREEN**

Run:

```bash
./scripts/test-backend tests/test_decision_types.py -q
```

Expected:

```text
PASS
```

## Task 3: Add DecisionContextBuilder Shell and Input Contract

**Files:**
- Create: `backend/src/fitmas/decision/context_builder.py`
- Modify: `backend/src/fitmas/decision/__init__.py`
- Create: `tests/test_decision_context_builder.py`

- [ ] **Step 1: Write failing tests for builder input and no-user error**

Create `tests/test_decision_context_builder.py`:

```python
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-decision-context-", suffix=".db"))

from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.decision import InputEvent
from fitmas.decision.context_builder import (
    ContextBuilderInput,
    DecisionContextBuilder,
    DecisionContextUserNotFoundError,
)


def setup_function() -> None:
    init_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()


def test_context_builder_raises_when_event_user_does_not_exist() -> None:
    db = SessionLocal()
    try:
        event = InputEvent(
            id="evt_missing",
            user_id=999,
            source="telegram",
            type="user_message",
            text="hello",
            payload={},
            occurred_at=datetime(2026, 5, 14, 6, 30, tzinfo=timezone.utc),
        )

        with pytest.raises(DecisionContextUserNotFoundError):
            DecisionContextBuilder(db).build(ContextBuilderInput(event=event))
    finally:
        db.close()
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
./scripts/test-backend tests/test_decision_context_builder.py::test_context_builder_raises_when_event_user_does_not_exist -q
```

Expected:

```text
FAIL because fitmas.decision.context_builder does not exist.
```

- [ ] **Step 3: Implement builder shell**

Create `backend/src/fitmas/decision/context_builder.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from fitmas import repository as repo, schema as s
from fitmas.time_context import build_time_context, get_local_now

from .context import (
    AthleteContext,
    CoachContext,
    ExecutionReality,
    LoadContext,
    LocalTimeContext,
    MemoryContext,
    PendingContext,
    PlanTimeline,
    ReadinessContext,
    WeeklyRealityDigest,
)
from .input_event import InputEvent


@dataclass(frozen=True, slots=True)
class ContextBuilderInput:
    event: InputEvent
    now: datetime | None = None
    screen: str = "decision_runtime"
    scheduled_sessions_limit: int = 84
    activities_limit: int = 500
    recent_adaptations_limit: int = 6


class DecisionContextUserNotFoundError(RuntimeError):
    pass


class DecisionContextBuilder:
    def __init__(self, db: Session) -> None:
        self._db = db

    def build(self, request: ContextBuilderInput) -> CoachContext:
        user = self._db.get(s.User, request.event.user_id)
        if user is None:
            raise DecisionContextUserNotFoundError(f"user_id={request.event.user_id} not found")

        local_now = get_local_now(user.timezone, now=request.now)
        time_context = build_time_context(user.timezone, now=request.now)

        return CoachContext(
            user=user,
            local_time=LocalTimeContext(
                timezone_name=user.timezone or "Europe/Paris",
                now_iso=local_now.isoformat(timespec="minutes"),
                today_iso=local_now.date().isoformat(),
                time_context=time_context,
            ),
            plan=PlanTimeline(
                scheduled_sessions=(),
                session_policies=(),
                planning_contract=None,
                week_mission=None,
                latest_adaptation=None,
                recent_adaptations=(),
            ),
            execution=ExecutionReality(activities=(), recent_reality=None, today_execution=None),
            memory=MemoryContext(active_memory=(), active_facts=()),
            athlete=AthleteContext(profile_snapshot=None, calibration_status=None),
            readiness=ReadinessContext(snapshot=None, state=None),
            load=LoadContext(summary=None, forecast=None),
            weekly_digest=WeeklyRealityDigest(
                week_summary={},
                planning_context={},
                next_week={},
                coach_reading="",
            ),
            pending=PendingContext(active_pending=None, summary=None),
        )
```

This shell intentionally uses only the user/time reads. The next task fills domain truth.

- [ ] **Step 4: Keep builder out of root package exports**

Do not import `context_builder` in `backend/src/fitmas/decision/__init__.py`.

```python
assert "context_builder" not in (DECISION / "__init__.py").read_text(encoding="utf-8")
```

Reason: `context_builder.py` is the only Phase 2 decision module allowed to
read DB/repository state. Importing it from package root would make
`import fitmas.decision` load DB-facing dependencies.

- [ ] **Step 5: Run builder shell tests**

Run:

```bash
./scripts/test-backend tests/test_decision_context_builder.py tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
PASS for the no-user behavior and import boundary except the architecture test may still fail because context_builder does not read repository yet.
```

If the architecture test requires repository reads at this point, move the repository import expectation to Task 4.

## Task 4: Build CoachContext From Existing Truth

**Files:**
- Modify: `backend/src/fitmas/decision/context_builder.py`
- Modify: `tests/test_decision_context_builder.py`

- [ ] **Step 1: Write failing test for canonical DB-backed context**

Add:

```python
from fitmas import repository as repo, schema as s
from fitmas.time_context import DAY_KEYS, day_label_fr


def _plan_day(day_key: str) -> dict:
    return {
        "day": day_key,
        "label": day_label_fr(day_key, capitalize=True),
        "sport_type": "running",
        "session_type": "easy",
        "session_title": "Footing facile",
        "session_goal": "Relancer propre",
        "session_note": "",
        "session_description": "Footing Z2",
        "duration_min": 40,
        "intensity": "easy",
        "load_score": 2,
        "priority": "Normal",
        "nutrition_focus": "",
        "flexibility": "flexible",
        "completion_status": "planned",
    }


def test_context_builder_builds_canonical_context_from_scheduled_runtime_truth() -> None:
    db = SessionLocal()
    try:
        user = s.User(name="Loic", timezone="Europe/Paris", coach_name="FitMAS", coach_style="direct")
        db.add(user)
        db.commit()
        db.refresh(user)

        now = datetime(2026, 5, 14, 6, 30, tzinfo=timezone.utc)
        local_today = now.astimezone(timezone.utc).date()
        today_key = DAY_KEYS[local_today.weekday()]
        repo.replace_plan(
            db,
            user.id,
            intention="reprendre propre",
            summary="test",
            timezone_name=user.timezone,
            days=[_plan_day(today_key)],
        )
        session = repo.get_scheduled_sessions(db, user.id, limit=10)[0]
        event = InputEvent(
            id="evt_1",
            user_id=user.id,
            source="telegram",
            type="user_message",
            text="j'ai quoi aujourd'hui ?",
            payload={"client_message_key": "telegram:1"},
            occurred_at=now,
        )

        context = DecisionContextBuilder(db).build(ContextBuilderInput(event=event, now=now))

        assert context.user.id == user.id
        assert context.local_time.timezone_name == "Europe/Paris"
        assert context.plan.scheduled_sessions == (session,)
        assert context.plan.planning_contract is not None
        assert context.plan.week_mission is not None
        assert context.execution.activities == ()
        assert context.memory.active_memory == ()
        assert context.athlete.profile_snapshot is not None
        assert context.athlete.calibration_status is not None
        assert context.execution.recent_reality is not None
        assert context.weekly_digest.week_summary["total_sessions"] == 1
        assert context.weekly_digest.coach_reading.strip()
    finally:
        db.close()
```

Note: if timezone math makes `today_key` brittle, derive `today_key` from `get_local_now(user.timezone, now=now)` in the test.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
./scripts/test-backend tests/test_decision_context_builder.py::test_context_builder_builds_canonical_context_from_scheduled_runtime_truth -q
```

Expected:

```text
FAIL because the shell builder returns empty plan/execution/memory/athlete fields.
```

- [ ] **Step 3: Fill the builder using existing read models**

Update `DecisionContextBuilder.build()`:

```python
from fitmas.coach_state_bundle import build_coach_state_bundle

...

scheduled_sessions = tuple(
    repo.get_scheduled_sessions(
        self._db,
        user.id,
        limit=request.scheduled_sessions_limit,
    )
)
activities = tuple(repo.get_activities(self._db, user.id, limit=request.activities_limit))
planning_decision = repo.get_latest_planning_decision_record(self._db, user.id)
readiness_row = repo.get_latest_readiness_snapshot_record(self._db, user.id)
readiness = repo.to_domain_readiness_snapshot(readiness_row) if readiness_row else None
coach_bundle = build_coach_state_bundle(
    self._db,
    user=user,
    today_date=local_now.date(),
    scheduled_sessions=list(scheduled_sessions),
    activities=list(activities),
    planning_decision=planning_decision,
    recent_adaptations_limit=request.recent_adaptations_limit,
    readiness=readiness,
    screen=request.screen,
)

return CoachContext(
    user=user,
    local_time=...,
    plan=PlanTimeline(
        scheduled_sessions=scheduled_sessions,
        session_policies=coach_bundle.session_policies,
        planning_contract=coach_bundle.planning_contract,
        week_mission=coach_bundle.week_mission,
        latest_adaptation=coach_bundle.latest_adaptation,
        recent_adaptations=coach_bundle.recent_adaptations,
    ),
    execution=ExecutionReality(
        activities=activities,
        recent_reality=coach_bundle.recent_reality,
        today_execution=None,
    ),
    memory=MemoryContext(active_memory=coach_bundle.active_memory, active_facts=()),
    athlete=AthleteContext(
        profile_snapshot=coach_bundle.profile_snapshot,
        calibration_status=coach_bundle.calibration_status,
    ),
    readiness=ReadinessContext(snapshot=readiness, state=None),
    load=LoadContext(summary=None, forecast=None),
    weekly_digest=WeeklyRealityDigest(
        week_summary=coach_bundle.week_summary,
        planning_context=coach_bundle.planning_context,
        next_week=coach_bundle.next_week,
        coach_reading=coach_bundle.coach_reading,
    ),
    pending=PendingContext(active_pending=None, summary=None),
)
```

Do not call `repo.get_active_plan`, `repo.to_pydantic_plan`, `repo.get_day_plan`, `WeeklyPlan` or `DayPlan`.

- [ ] **Step 4: Run builder tests**

Run:

```bash
./scripts/test-backend tests/test_decision_context_builder.py -q
```

Expected:

```text
PASS
```

## Task 5: Lock Runtime Non-Integration

**Files:**
- Modify: `tests/test_decision_runtime_architecture.py`

- [ ] **Step 1: Add explicit no-branch imports for existing runtime files**

If Task 1 did not already add this, add:

```python
def test_phase2_does_not_wire_existing_runtime_to_context_builder() -> None:
    root = ROOT / "backend" / "src" / "fitmas"
    files = [
        root / "conversation_pipeline.py",
        root / "skills" / "heartbeat" / "heartbeat.py",
        root / "api_app.py",
        root / "api_messages.py",
    ]
    offenders: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        if "DecisionContextBuilder" in source or "fitmas.decision.context_builder" in source:
            offenders.append(path.name)

    assert offenders == []
```

- [ ] **Step 2: Run architecture tests**

Run:

```bash
./scripts/test-backend tests/test_decision_runtime_architecture.py -q
```

Expected:

```text
PASS
```

## Task 6: Update Docs After Verification

**Files:**
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/BUILD-ORDER.md`

- [ ] **Step 1: Update Decision Runtime doc**

Add under `Etat implementation — 14 mai 2026`:

```markdown
Phase 2 demarree localement :

- `CoachContext` est maintenant decoupe en contextes domaines (`LocalTimeContext`, `PlanTimeline`, `ExecutionReality`, `MemoryContext`, `AthleteContext`, `ReadinessContext`, `LoadContext`, `WeeklyRealityDigest`, `PendingContext`) ;
- `DecisionContextBuilder` construit un `CoachContext` depuis `InputEvent + DB` en lecture seule ;
- le builder reutilise `CoachStateBundle` mais ne lit pas `WeeklyPlan/DayPlan` comme verite runtime ;
- aucun runtime existant n'est branche sur ce builder.
```

- [ ] **Step 2: Update Build Order**

In `Roadmap Active — 14 mai 2026`, update the status:

```markdown
- Phase 2 initiale livree localement :
  - `DecisionContextBuilder` read-only ;
  - `CoachContext` canonique par domaines ;
  - tests de non-integration runtime ;
  - aucun changement comportemental.
```

- [ ] **Step 3: Run docs list**

Run:

```bash
./scripts/docs:list | rg -n "DECISION-RUNTIME|BUILD-ORDER|Reminder"
```

Expected:

```text
DECISION-RUNTIME-REFACTOR.md and BUILD-ORDER.md are listed.
```

## Task 7: Verification Gate

**Files:**
- No edits unless a test exposes a real issue.

- [ ] **Step 1: Run Phase 2 targeted tests**

Run:

```bash
./scripts/test-backend tests/test_decision_types.py tests/test_decision_runtime_architecture.py tests/test_decision_context_builder.py tests/test_coach_state_bundle.py tests/test_context_pack.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 2: Run existing boundary tests**

Run:

```bash
./scripts/test-backend tests/test_llm_first_conversation_contract.py tests/test_phase3_legacy_reads.py tests/test_plan_actions_truth.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 3: Run full backend suite**

Run:

```bash
./scripts/test-backend -q
```

Expected:

```text
All tests pass. Current Phase 0/1 baseline was 987 passed, 11 skipped, 11 subtests passed; count may increase by the new Phase 2 tests.
```

- [ ] **Step 4: Review diff for forbidden scope**

Run:

```bash
git diff -- backend/src/fitmas/decision tests/test_decision_types.py tests/test_decision_runtime_architecture.py tests/test_decision_context_builder.py docs/DECISION-RUNTIME-REFACTOR.md docs/BUILD-ORDER.md
git status --short
```

Verify:

- no `conversation_pipeline.py` diff;
- no heartbeat/app route integration diff;
- no prompt file diff;
- no tool registry diff;
- no `PlanPatch` / `MutationDecision` import in `decision/`;
- no `WeeklyPlan` / `DayPlan` dependency in `context_builder.py`;
- docs reflect local status only.

## Acceptance Criteria

Phase 2 is accepted when:

- `CoachContext` is no longer a bag of `Any` fields at the top level;
- `DecisionContextBuilder` exists and builds a non-empty `CoachContext` from real DB rows;
- `DecisionContextBuilder` is read-only;
- `context_builder.py` does not call `get_active_plan`, `to_pydantic_plan`, `get_day_plan`, `WeeklyPlan` or `DayPlan`;
- pure decision modules still have no DB/SQLAlchemy/repository/schema imports;
- existing runtime files are not wired to `DecisionContextBuilder`;
- targeted and full backend tests pass;
- docs mark Phase 2 status without claiming later phases.

## Execution Recommendation

Run Phase 2 as one sequential slice, not parallel subagents.

Reason:

- `context.py`, `context_builder.py`, `__init__.py` and architecture tests are tightly coupled;
- parallel workers would likely fight over the same files;
- this is still foundation work.

Use a fresh implementation agent if desired, but give it this exact plan and the invariants above. Review after each task before proceeding.
