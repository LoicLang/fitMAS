---
summary: implementation plan for Decision Runtime Phase 8F command extraction
read_when:
  - implementing Decision Runtime Phase 8F
  - moving memory_actions or execution_actions behind CommandBus
  - extracting conversation writes from conversation_pipeline.py
  - preparing CoachUnderstanding signals for command drafts
  - shrinking CoachDecision toward provider compatibility only
---

# Decision Runtime Phase 8F Command Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route conversation memory/execution writes through canonical `Command` + `CommandBus`, expose event-backed `CommandResult`s, and prepare canonical `CoachUnderstanding` signal command drafts without deleting legacy `CoachDecision` yet.

**Architecture:** 8F is the command boundary slice. `conversation_pipeline.py` delegates typed action application to a legacy bridge; the bridge compiles typed artifacts into `decision.Command` objects; a conversation `CommandBus` applies those commands through the existing mutation services and returns event-backed results. Canonical Understanding command compilation is introduced behind an explicit flag, while legacy `CoachDecision` remains the default provider source for memory/execution until parity is proven.

**Tech Stack:** Python 3.13, dataclasses, pytest/unittest, existing `fitmas.decision.CommandBus`, existing `memory_mutation_service`, existing `execution_mutation_service`, existing `CoachDecision` action models, architecture tests.

---

## CTO Decision

8F is the point where the refactor starts touching write paths.

Do **not** delete `CoachDecision` in this phase. It still carries:

```text
- memory_actions
- execution_actions
- pending_resolution
- legacy provider compatibility for old tests
```

The useful move is narrower:

```text
legacy CoachDecision actions
or canonical CoachUnderstanding signals under flag
  -> Command objects
  -> ConversationCommandBus
  -> existing command services
  -> event-backed CommandResult
  -> metrics + turn_memory_writes
```

This makes the runtime boundary real without forcing a risky provider swap.

## Scope

8F includes:

```text
1. Memory writes from CoachDecision actions go through CommandBus.
2. Execution writes from CoachDecision actions go through CommandBus.
3. Turn-plan availability memory writes go through CommandBus.
4. CommandResult for applied commands references a persisted event id.
5. conversation_pipeline.py no longer imports memory/execution mutation services.
6. CoachUnderstanding signal-to-command compilation exists behind a flag.
7. Docs and architecture gates record the remaining pending_resolution debt.
```

8F does **not** include:

```text
1. Removing CoachDecision.
2. Removing pending_resolution.
3. Replacing the full legacy decide provider.
4. Rewriting final_reply.py.
5. Moving the root mutation service files into domain/ packages.
6. Changing user-visible behavior by default.
```

Pending resolution remains the main reason `CoachDecision` survives after 8F. That becomes the center of 8G.

## Non-Negotiables

```text
1. No deterministic parsing of free user text.
2. Command adapters consume typed artifacts only: CoachDecision actions, CoachUnderstanding signals, turn_plan artifacts.
3. decision/ stays pure: no DB, no legacy, no llm provider, no conversation imports.
4. conversation_pipeline.py must not call apply_memory_actions_for_user directly.
5. conversation_pipeline.py must not call apply_execution_actions_for_user directly.
6. No duplicate writes: one action becomes one command application path.
7. Applied CommandResult must include an event id.
8. New bridge code lives in legacy/ until the full runtime cutover is complete.
9. Canonical Understanding commands are opt-in, not default, in 8F.
10. Existing dogfood behavior remains stable when the canonical command flag is off.
```

## Flags

Add one flag.

```text
FITMAS_COMMANDS_FROM_UNDERSTANDING
  default: off
  effect: compile memory/execution command drafts from canonical CoachUnderstanding
          when available, instead of legacy CoachDecision action fields
```

This flag requires `FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1` to produce a canonical understanding in the conversation turn.

Do not add a flag for the CommandBus itself. The bus is the new application boundary; it delegates to the same mutation services, so behavior should remain equivalent.

## File Map

Create:

```text
backend/src/fitmas/legacy/coach_command_adapter.py
backend/src/fitmas/legacy/conversation_command_bus.py
backend/src/fitmas/legacy/conversation_command_bridge.py
tests/test_phase8f_command_extraction_architecture.py
tests/test_coach_command_adapter.py
tests/test_conversation_command_bus.py
tests/test_conversation_command_bridge.py
```

Modify:

```text
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/memory_mutation_service.py
backend/src/fitmas/execution_mutation_service.py
backend/src/fitmas/llm/prompts/understanding.py
docs/DECISION-RUNTIME-REFACTOR.md
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/BUILD-ORDER.md
docs/README.md
```

Do not modify in 8F unless a failing test proves it is necessary:

```text
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/final_reply.py
backend/src/fitmas/plan_mutation_service.py
backend/src/fitmas/tools/registry.py
```

## Target Flow

```text
conversation_pipeline.py
  -> conversation_command_bridge.apply_turn_plan_memory_commands(...)
  -> conversation_command_bridge.apply_coach_decision_commands(...)
      -> coach_command_adapter.commands_from_legacy_decision(...)
      -> ConversationCommandBus.apply(...)
          -> memory_mutation_service.apply_memory_actions_for_user(...)
          -> execution_mutation_service.apply_execution_actions_for_user(...)
      -> ConversationCommandApplication metrics
```

When the canonical flag is enabled:

```text
canonical CoachUnderstanding
  -> coach_command_adapter.commands_from_understanding(...)
  -> ConversationCommandBus.apply(...)
```

The bridge may fall back to legacy decision actions only when canonical command compilation is disabled or unavailable.

---

## Task 1 — 8F Architecture Gates

**Files:**

- Create: `tests/test_phase8f_command_extraction_architecture.py`

- [ ] **Step 1: Write failing architecture tests**

Create `tests/test_phase8f_command_extraction_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(relative: str) -> set[str]:
    tree = ast.parse((SRC / relative).read_text(encoding="utf-8"), filename=relative)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_8f_conversation_pipeline_no_longer_imports_action_writers() -> None:
    source = _source("conversation_pipeline.py")
    imports = _imports("conversation_pipeline.py")

    assert "fitmas.memory_mutation_service" not in imports
    assert "fitmas.execution_mutation_service" not in imports
    assert "apply_memory_actions_for_user" not in source
    assert "apply_execution_actions_for_user" not in source
    assert "conversation_command_bridge" in source


def test_8f_command_bridge_is_the_only_conversation_action_application_boundary() -> None:
    source = _source("legacy/conversation_command_bridge.py")
    imports = _imports("legacy/conversation_command_bridge.py")

    assert "apply_coach_decision_commands" in source
    assert "apply_turn_plan_memory_commands" in source
    assert "ConversationCommandBus" in source
    assert "fitmas.conversation_pipeline" not in imports
    assert "fitmas.memory_mutation_service" not in imports
    assert "fitmas.execution_mutation_service" not in imports


def test_8f_command_bus_is_the_only_new_legacy_writer_adapter() -> None:
    source = _source("legacy/conversation_command_bus.py")
    imports = _imports("legacy/conversation_command_bus.py")

    assert "class ConversationCommandBus" in source
    assert "fitmas.decision" in imports
    assert "fitmas.memory_mutation_service" in imports
    assert "fitmas.execution_mutation_service" in imports
    assert "fitmas.conversation_pipeline" not in imports


def test_8f_coach_command_adapter_does_not_write_or_parse_user_text() -> None:
    source = _source("legacy/coach_command_adapter.py")
    imports = _imports("legacy/coach_command_adapter.py")

    assert "commands_from_legacy_decision" in source
    assert "commands_from_understanding" in source
    assert "fitmas.decision" in imports
    assert "fitmas.memory_mutation_service" not in imports
    assert "fitmas.execution_mutation_service" not in imports
    assert ".commit(" not in source
    assert "re.search" not in source
    assert "regex" not in source.lower()


def test_8f_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.memory_mutation_service",
        "fitmas.execution_mutation_service",
        "fitmas.conversation_pipeline",
    }
    for path in (SRC / "decision").glob("*.py"):
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"
```

- [ ] **Step 2: Run architecture tests and verify failure**

Run:

```bash
./scripts/test-backend -q tests/test_phase8f_command_extraction_architecture.py
```

Expected: failure because the new bridge files do not exist and `conversation_pipeline.py` still imports the action writers.

- [ ] **Step 3: Commit only after the later implementation makes this pass**

No commit after this failing test alone.

---

## Task 2 — Event IDs From Existing Mutation Services

**Files:**

- Modify: `backend/src/fitmas/memory_mutation_service.py`
- Modify: `backend/src/fitmas/execution_mutation_service.py`
- Modify: `tests/test_memory_mutation_service.py`

- [ ] **Step 1: Extend existing tests for event ids**

In `tests/test_memory_mutation_service.py`, update `test_memory_service_routes_actions_to_bounded_memory_and_audit`:

```python
self.assertEqual(len(result.event_ids), 2)
self.assertEqual(tuple(event.id for event in events), result.event_ids)
```

Update `test_execution_service_marks_unique_target_skipped_and_audits`:

```python
self.assertEqual(len(result.event_ids), 1)
self.assertEqual(result.event_ids[0], events[0].id)
```

Update `test_execution_service_refuses_ambiguous_target_without_write`:

```python
self.assertEqual(len(result.event_ids), 1)
self.assertEqual(result.event_ids[0], events[0].id)
```

- [ ] **Step 2: Run the targeted tests and verify failure**

Run:

```bash
./scripts/test-backend -q tests/test_memory_mutation_service.py
```

Expected: failure with `AttributeError: 'MemoryActionApplicationResult' object has no attribute 'event_ids'`.

- [ ] **Step 3: Add event ids to service result dataclasses**

In `backend/src/fitmas/memory_mutation_service.py`:

```python
@dataclass(frozen=True, slots=True)
class MemoryActionApplicationResult:
    applied_count: int
    blocked_count: int
    saved_keys: tuple[str, ...]
    event_ids: tuple[int, ...] = ()
```

In `backend/src/fitmas/execution_mutation_service.py`:

```python
@dataclass(frozen=True, slots=True)
class ExecutionActionApplicationResult:
    applied_count: int
    blocked_count: int
    updated_session_ids: tuple[int, ...]
    event_ids: tuple[int, ...] = ()
```

- [ ] **Step 4: Return event ids from memory events**

In `backend/src/fitmas/memory_mutation_service.py`, collect ids:

```python
event_ids: list[int] = []
```

For blocked invalid memory actions, replace:

```python
_add_event(
```

with:

```python
event_ids.append(_add_event(
```

and close the call with `))`.

For applied memory payloads, replace:

```python
_add_event(
```

with:

```python
event_ids.append(_add_event(
```

and close the call with `))`.

Pass `event_ids` into `_resolve_overlapping_unavailability` and extend it when availability rows are resolved:

```python
event_ids.extend(
    _resolve_overlapping_unavailability(
        db,
        user=user,
        action=action,
        source=source,
        conversation_turn_id=conversation_turn_id,
        now=now,
    )
)
```

Change `_resolve_overlapping_unavailability` to return ids:

```python
def _resolve_overlapping_unavailability(...) -> tuple[int, ...]:
    ...
    if starts_on is None or ends_on is None:
        return ()
    ...
    if not resolved_rows:
        return ()
    db.commit()
    event_ids: list[int] = []
    for row in resolved_rows:
        event_ids.append(_add_event(...))
    return tuple(event_ids)
```

Change `_add_event` to return an id:

```python
def _add_event(...) -> int:
    record = s.MemoryMutationEventRecord(
        user_id=user.id,
        source=source,
        action_type=action_type,
        target_type=target_type,
        target_key=target_key,
        status=status,
        reason=reason,
        payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str),
        conversation_turn_id=conversation_turn_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return int(record.id)
```

Return:

```python
return MemoryActionApplicationResult(
    applied_count=len(saved_profile) + len(saved_working),
    blocked_count=blocked,
    saved_keys=saved_keys,
    event_ids=tuple(event_ids),
)
```

- [ ] **Step 5: Return event ids from execution events**

In `backend/src/fitmas/execution_mutation_service.py`, add:

```python
event_ids: list[int] = []
```

For each `_add_event(...)` call, append the return value:

```python
event_ids.append(_add_event(...))
```

Change `_add_event`:

```python
def _add_event(...) -> int:
    payload = action.model_dump(mode="json")
    if target_session_id is not None:
        payload["target_session_id"] = target_session_id
    record = s.MemoryMutationEventRecord(
        user_id=user.id,
        source=source,
        action_type=action.type,
        target_type="scheduled_session",
        target_key=str(target_session_id or ""),
        status=status,
        reason=reason,
        payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True),
        conversation_turn_id=conversation_turn_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return int(record.id)
```

Return:

```python
return ExecutionActionApplicationResult(
    applied_count=applied,
    blocked_count=blocked,
    updated_session_ids=tuple(updated_ids),
    event_ids=tuple(event_ids),
)
```

- [ ] **Step 6: Run service tests**

Run:

```bash
./scripts/test-backend -q tests/test_memory_mutation_service.py
```

Expected: pass.

---

## Task 3 — Coach Command Adapter

**Files:**

- Create: `backend/src/fitmas/legacy/coach_command_adapter.py`
- Create: `tests/test_coach_command_adapter.py`

- [ ] **Step 1: Write adapter tests**

Create `tests/test_coach_command_adapter.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.decision import CoachUnderstanding, RequestedPlanChange, UserSignal
from fitmas.legacy.coach_command_adapter import (
    commands_from_legacy_decision,
    commands_from_understanding,
    execution_action_from_command,
    memory_action_from_command,
)
from fitmas.llm import AvailabilityConstraintAction, CoachDecision, ExecutionUpdateAction, HealthSignalAction


def test_legacy_decision_memory_and_execution_actions_become_commands() -> None:
    decision = CoachDecision(
        response_type="reply",
        rationale="typed actions should become commands",
        fitmas_message="ok",
        memory_actions=(
            HealthSignalAction(
                type="record_health_signal",
                health_signal="douleur genou",
                body_area="genou",
                status="ongoing",
                severity="moderate",
                signal_kind="pain",
                confidence=0.9,
                evidence="mal au genou",
            ),
        ),
        execution_actions=(
            ExecutionUpdateAction(
                type="record_execution_update",
                target_ref="2026-05-13",
                status="not_completed",
                completed=False,
                sport_type="strength",
                confidence=0.9,
                evidence="pas fait",
            ),
        ),
    )

    bundle = commands_from_legacy_decision(decision, turn_plan=None)

    assert [command.domain for command in bundle.commands] == ["memory", "execution"]
    assert bundle.deferred_execution_count == 0
    assert memory_action_from_command(bundle.commands[0]).type == "record_health_signal"
    assert execution_action_from_command(bundle.commands[1]).type == "record_execution_update"


def test_turn_plan_availability_is_added_once_to_legacy_commands() -> None:
    decision = CoachDecision(
        response_type="reply",
        rationale="turn plan availability should become memory command",
        fitmas_message="ok",
    )
    turn_plan = SimpleNamespace(
        availability_constraint={
            "availability": "unavailable",
            "sport_type": "swimming",
            "scope": "sport",
            "starts_on": "2026-05-14",
            "ends_on": "2026-05-28",
        },
        confidence=0.82,
    )

    bundle = commands_from_legacy_decision(decision, turn_plan=turn_plan)

    assert len(bundle.commands) == 1
    action = memory_action_from_command(bundle.commands[0])
    assert isinstance(action, AvailabilityConstraintAction)
    assert action.availability == "unavailable"
    assert action.sport_type == "swimming"
    assert action.starts_on == "2026-05-14"
    assert action.ends_on == "2026-05-28"


def test_conflicting_execution_action_is_deferred_when_plan_patch_targets_same_session() -> None:
    execution_action = ExecutionUpdateAction(
        type="record_execution_update",
        target_ref="seance cible",
        target_session_id=42,
        status="not_completed",
        completed=False,
        confidence=0.9,
        evidence="pas fait",
    )
    availability_action = AvailabilityConstraintAction(
        type="record_availability",
        window_text="indispo",
        availability="unavailable",
        starts_on="2026-05-14",
        ends_on="2026-05-14",
        confidence=0.9,
        evidence="indispo",
    )
    patch = SimpleNamespace(operations=(SimpleNamespace(target_session_id=42),))
    decision = CoachDecision(
        response_type="requires_confirmation",
        rationale="availability plus plan patch should defer matching execution action",
        fitmas_message="ok",
        plan_patch=patch,
        memory_actions=(availability_action,),
        execution_actions=(execution_action,),
    )

    bundle = commands_from_legacy_decision(decision, turn_plan=None)

    assert [command.domain for command in bundle.commands] == ["memory"]
    assert bundle.deferred_execution_count == 1


def test_understanding_signals_compile_to_commands_from_payload_only() -> None:
    understanding = CoachUnderstanding(
        intent="availability_signal",
        confidence=0.9,
        user_summary="piscine impossible deux semaines",
        extracted_signals=(
            UserSignal(
                type="availability",
                label="natation indisponible",
                status="new",
                severity="high",
                confidence=0.91,
                evidence="je ne peux pas nager deux semaines",
                payload={
                    "action_type": "record_availability",
                    "availability": "unavailable",
                    "window_text": "natation impossible deux semaines",
                    "sport_type": "swimming",
                    "scope": "sport",
                    "starts_on": "2026-05-14",
                    "ends_on": "2026-05-28",
                },
            ),
        ),
        requested_change=RequestedPlanChange(
            kind="unknown",
            source_ref=None,
            target_ref=None,
            desired_sport=None,
            desired_duration_min=None,
            desired_intensity=None,
            reason="availability",
            risk_signals=(),
        ),
        pending_resolution=None,
        clarification_need=None,
    )

    bundle = commands_from_understanding(understanding)

    assert len(bundle.commands) == 1
    action = memory_action_from_command(bundle.commands[0])
    assert isinstance(action, AvailabilityConstraintAction)
    assert action.availability == "unavailable"
    assert action.sport_type == "swimming"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
./scripts/test-backend -q tests/test_coach_command_adapter.py
```

Expected: failure because `legacy/coach_command_adapter.py` does not exist.

- [ ] **Step 3: Implement adapter dataclass and public functions**

Create `backend/src/fitmas/legacy/coach_command_adapter.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from fitmas.decision import CoachUnderstanding, Command, UserSignal
from fitmas.llm import (
    AvailabilityConstraintAction,
    ExecutionUpdateAction,
    HealthSignalAction,
    MemoryAction,
    PreferenceSignalAction,
)


@dataclass(frozen=True, slots=True)
class CoachCommandBundle:
    commands: tuple[Command, ...]
    deferred_execution_count: int = 0
    source: str = "coach_decision"


def commands_from_legacy_decision(decision: Any, *, turn_plan: Any | None) -> CoachCommandBundle:
    memory_actions = tuple(getattr(decision, "memory_actions", ()) or ())
    memory_actions = _memory_actions_with_turn_plan_availability(
        memory_actions=memory_actions,
        turn_plan=turn_plan,
    )
    execution_actions = tuple(getattr(decision, "execution_actions", ()) or ())
    execution_actions, deferred_execution_count = _defer_conflicting_execution_actions(
        decision=decision,
        memory_actions=memory_actions,
        execution_actions=execution_actions,
    )
    return CoachCommandBundle(
        commands=(
            *_commands_from_memory_actions(memory_actions),
            *_commands_from_execution_actions(execution_actions),
        ),
        deferred_execution_count=deferred_execution_count,
        source="coach_decision",
    )


def commands_from_understanding(understanding: CoachUnderstanding) -> CoachCommandBundle:
    memory_actions: list[MemoryAction] = []
    execution_actions: list[ExecutionUpdateAction] = []
    for signal in understanding.extracted_signals:
        if signal.type in {"health", "availability", "preference"}:
            action = _memory_action_from_signal(signal)
            if action is not None:
                memory_actions.append(action)
        elif signal.type == "execution":
            action = _execution_action_from_signal(signal)
            if action is not None:
                execution_actions.append(action)
    return CoachCommandBundle(
        commands=(
            *_commands_from_memory_actions(tuple(memory_actions)),
            *_commands_from_execution_actions(tuple(execution_actions)),
        ),
        deferred_execution_count=0,
        source="coach_understanding",
    )
```

- [ ] **Step 4: Implement command serialization and reconstruction**

Add to `backend/src/fitmas/legacy/coach_command_adapter.py`:

```python
def memory_action_from_command(command: Command) -> MemoryAction:
    action_type = str(command.payload.get("type") or command.payload.get("action_type") or command.name)
    payload = dict(command.payload)
    payload["type"] = action_type
    if action_type == "record_health_signal":
        return HealthSignalAction(**payload)
    if action_type == "record_availability":
        return AvailabilityConstraintAction(**payload)
    if action_type == "record_preference":
        return PreferenceSignalAction(**payload)
    raise ValueError(f"unsupported memory command: {action_type}")


def execution_action_from_command(command: Command) -> ExecutionUpdateAction:
    payload = dict(command.payload)
    payload["type"] = str(command.payload.get("type") or command.payload.get("action_type") or command.name)
    return ExecutionUpdateAction(**payload)


def _commands_from_memory_actions(actions: Iterable[MemoryAction]) -> tuple[Command, ...]:
    commands: list[Command] = []
    for index, action in enumerate(actions):
        commands.append(
            Command(
                id=f"memory:{index}:{getattr(action, 'type', 'unknown')}",
                domain="memory",
                name=str(getattr(action, "type", "") or "memory_action"),
                payload=_action_payload(action),
            )
        )
    return tuple(commands)


def _commands_from_execution_actions(actions: Iterable[ExecutionUpdateAction]) -> tuple[Command, ...]:
    commands: list[Command] = []
    for index, action in enumerate(actions):
        commands.append(
            Command(
                id=f"execution:{index}:{getattr(action, 'type', 'unknown')}",
                domain="execution",
                name=str(getattr(action, "type", "") or "execution_action"),
                payload=_action_payload(action),
            )
        )
    return tuple(commands)


def _action_payload(action: Any) -> dict[str, Any]:
    if hasattr(action, "model_dump"):
        return dict(action.model_dump(mode="json", exclude_none=True))
    return {}
```

- [ ] **Step 5: Move existing typed helper logic from conversation_pipeline**

Move these helpers from `conversation_pipeline.py` to `legacy/coach_command_adapter.py` without changing behavior:

```text
_memory_actions_with_turn_plan_availability
_availability_actions_match
_defer_conflicting_execution_actions
_has_availability_memory_action
_plan_patch_session_ids
_availability_memory_action_from_turn_plan
_clean_enum_value
_clean_optional_artifact_value
_availability_window_text
_normalized_pending_value
```

The moved `_availability_memory_action_from_turn_plan` must instantiate `AvailabilityConstraintAction` imported from `fitmas.llm`, not `llm_runtime.AvailabilityConstraintAction`.

- [ ] **Step 6: Implement signal compilers**

Add to `backend/src/fitmas/legacy/coach_command_adapter.py`:

```python
def _memory_action_from_signal(signal: UserSignal) -> MemoryAction | None:
    payload = dict(signal.payload)
    action_type = str(payload.get("action_type") or payload.get("type") or "").strip()
    common = {
        "confidence": float(payload.get("confidence") or signal.confidence),
        "evidence": str(payload.get("evidence") or signal.evidence or ""),
    }
    if action_type == "record_health_signal":
        return HealthSignalAction(
            type="record_health_signal",
            health_signal=str(payload.get("health_signal") or signal.label),
            body_area=_optional_str(payload.get("body_area")),
            status=_health_status(payload.get("status") or signal.status),
            severity=_health_severity(payload.get("severity") or signal.severity),
            signal_kind=str(payload.get("signal_kind") or "health"),
            **common,
        )
    if action_type == "record_availability":
        return AvailabilityConstraintAction(
            type="record_availability",
            window_text=str(payload.get("window_text") or signal.label),
            availability=str(payload.get("availability") or "unknown"),
            sport_type=_optional_str(payload.get("sport_type")),
            scope=_optional_str(payload.get("scope")),
            starts_on=_optional_str(payload.get("starts_on")),
            ends_on=_optional_str(payload.get("ends_on")),
            **common,
        )
    if action_type == "record_preference":
        return PreferenceSignalAction(
            type="record_preference",
            preference=str(payload.get("preference") or signal.label),
            polarity=str(payload.get("polarity") or "prefer"),
            scope=_optional_str(payload.get("scope")),
            **common,
        )
    return None


def _execution_action_from_signal(signal: UserSignal) -> ExecutionUpdateAction | None:
    payload = dict(signal.payload)
    action_type = str(payload.get("action_type") or payload.get("type") or "").strip()
    if action_type != "record_execution_update":
        return None
    return ExecutionUpdateAction(
        type="record_execution_update",
        target_ref=str(payload.get("target_ref") or ""),
        target_session_id=payload.get("target_session_id"),
        status=str(payload.get("status") or "unknown"),
        completed=payload.get("completed"),
        sport_type=_optional_str(payload.get("sport_type")),
        confidence=float(payload.get("confidence") or signal.confidence),
        evidence=str(payload.get("evidence") or signal.evidence or ""),
    )


def _optional_str(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"unknown", "null", "none"}:
        return None
    return text


def _health_status(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"new", "ongoing", "improving", "worsening", "resolved", "unknown"}:
        return cleaned
    if cleaned == "open":
        return "ongoing"
    return "unknown"


def _health_severity(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"mild", "moderate", "severe", "unknown"}:
        return cleaned
    if cleaned == "low":
        return "mild"
    if cleaned == "medium":
        return "moderate"
    if cleaned == "high":
        return "severe"
    return "unknown"
```

- [ ] **Step 7: Run adapter tests**

Run:

```bash
./scripts/test-backend -q tests/test_coach_command_adapter.py
```

Expected: pass.

---

## Task 4 — Conversation CommandBus

**Files:**

- Create: `backend/src/fitmas/legacy/conversation_command_bus.py`
- Create: `tests/test_conversation_command_bus.py`

- [ ] **Step 1: Write command bus tests**

Create `tests/test_conversation_command_bus.py` using the same database setup style as `tests/test_memory_mutation_service.py`:

```python
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-command-bus-", suffix=".db"))

from fitmas import repository as repo, schema as s
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.decision import Command
from fitmas.legacy.conversation_command_bus import ConversationCommandBus


class ConversationCommandBusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(name="Loic", timezone="Europe/Paris")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()

    def test_applies_memory_command_and_returns_event_backed_result(self) -> None:
        bus = ConversationCommandBus(db=self.db, user=self.user, source="coach_decision")
        command = Command(
            id="memory:0:record_availability",
            domain="memory",
            name="record_availability",
            payload={
                "type": "record_availability",
                "window_text": "piscine fermee",
                "availability": "unavailable",
                "sport_type": "swimming",
                "starts_on": "2026-05-14",
                "ends_on": "2026-05-28",
                "confidence": 0.9,
                "evidence": "piscine fermee",
            },
        )

        results = bus.apply((command,))

        events = self.db.query(s.MemoryMutationEventRecord).all()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "applied")
        self.assertEqual(results[0].event_id, f"memory_mutation_event:{events[0].id}")
        self.assertEqual(results[0].payload["saved_keys"], ("availability:unavailable_swimming_2026-05-14_2026-05-28",))

    def test_applies_execution_command_and_returns_updated_session(self) -> None:
        session = self._scheduled_session(days_offset=-1, sport_type="strength", title="Renfo")
        bus = ConversationCommandBus(db=self.db, user=self.user, source="coach_decision")
        command = Command(
            id="execution:0:record_execution_update",
            domain="execution",
            name="record_execution_update",
            payload={
                "type": "record_execution_update",
                "target_ref": session.scheduled_date.date().isoformat(),
                "status": "not_completed",
                "completed": False,
                "sport_type": "strength",
                "confidence": 0.95,
                "evidence": "pas fait",
            },
        )

        results = bus.apply((command,))

        updated = repo.get_scheduled_session(self.db, self.user.id, session.id)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "applied")
        self.assertEqual(results[0].payload["updated_session_ids"], (session.id,))
        self.assertEqual(updated.completion_status, "skipped")

    def _scheduled_session(self, *, days_offset: int, sport_type: str, title: str) -> s.ScheduledSession:
        target = datetime.now() + timedelta(days=days_offset)
        session = s.ScheduledSession(
            user_id=self.user.id,
            scheduled_date=target,
            sport_type=sport_type,
            session_type="easy",
            session_title=title,
            duration_min=30,
            completion_status="planned",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_command_bus.py
```

Expected: failure because `legacy/conversation_command_bus.py` does not exist.

- [ ] **Step 3: Implement `ConversationCommandBus`**

Create `backend/src/fitmas/legacy/conversation_command_bus.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.decision import Command, CommandResult
from fitmas.execution_mutation_service import apply_execution_actions_for_user
from fitmas.legacy.coach_command_adapter import execution_action_from_command, memory_action_from_command
from fitmas.memory_mutation_service import apply_memory_actions_for_user


@dataclass(slots=True)
class ConversationCommandBus:
    db: Session
    user: s.User
    source: str = "coach_decision"
    conversation_turn_id: int | None = None

    def apply(self, commands: Sequence[Command]) -> tuple[CommandResult, ...]:
        results: list[CommandResult] = []
        for command in commands:
            if command.domain == "memory":
                results.append(self._apply_memory(command))
            elif command.domain == "execution":
                results.append(self._apply_execution(command))
            else:
                results.append(
                    CommandResult(
                        command_id=command.id,
                        domain=command.domain,
                        name=command.name,
                        status="blocked",
                        event_id=None,
                        payload={"reason": "unsupported_domain"},
                    )
                )
        return tuple(results)
```

- [ ] **Step 4: Implement memory and execution application helpers**

Add:

```python
    def _apply_memory(self, command: Command) -> CommandResult:
        try:
            action = memory_action_from_command(command)
        except Exception as exc:
            return CommandResult(
                command_id=command.id,
                domain="memory",
                name=command.name,
                status="blocked",
                event_id=None,
                payload={"reason": "invalid_memory_command", "error": str(exc)[:160]},
            )
        result = apply_memory_actions_for_user(
            self.db,
            user=self.user,
            actions=(action,),
            source=self.source,
            conversation_turn_id=self.conversation_turn_id,
        )
        status = "applied" if result.applied_count > 0 else "blocked" if result.blocked_count > 0 else "skipped"
        return CommandResult(
            command_id=command.id,
            domain="memory",
            name=command.name,
            status=status,
            event_id=_event_ref(result.event_ids),
            payload={
                "applied_count": result.applied_count,
                "blocked_count": result.blocked_count,
                "saved_keys": result.saved_keys,
                "event_ids": result.event_ids,
                "summary": _memory_summary(result.saved_keys),
                "reason": "memory_action_blocked" if result.blocked_count else "",
            },
        )

    def _apply_execution(self, command: Command) -> CommandResult:
        try:
            action = execution_action_from_command(command)
        except Exception as exc:
            return CommandResult(
                command_id=command.id,
                domain="execution",
                name=command.name,
                status="blocked",
                event_id=None,
                payload={"reason": "invalid_execution_command", "error": str(exc)[:160]},
            )
        result = apply_execution_actions_for_user(
            self.db,
            user=self.user,
            actions=(action,),
            source=self.source,
            conversation_turn_id=self.conversation_turn_id,
        )
        status = "applied" if result.applied_count > 0 else "blocked" if result.blocked_count > 0 else "skipped"
        return CommandResult(
            command_id=command.id,
            domain="execution",
            name=command.name,
            status=status,
            event_id=_event_ref(result.event_ids),
            payload={
                "applied_count": result.applied_count,
                "blocked_count": result.blocked_count,
                "updated_session_ids": result.updated_session_ids,
                "event_ids": result.event_ids,
                "summary": _execution_summary(result.updated_session_ids),
                "reason": "execution_action_blocked" if result.blocked_count else "",
            },
        )


def _event_ref(event_ids: tuple[int, ...]) -> str | None:
    if not event_ids:
        return None
    return f"memory_mutation_event:{event_ids[0]}"


def _memory_summary(saved_keys: tuple[str, ...]) -> str:
    if not saved_keys:
        return ""
    return "Memoire mise a jour: " + ", ".join(saved_keys)


def _execution_summary(updated_session_ids: tuple[int, ...]) -> str:
    if not updated_session_ids:
        return ""
    ids = ", ".join(str(item) for item in updated_session_ids)
    return f"Execution mise a jour: session_id={ids}"
```

- [ ] **Step 5: Run command bus tests**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_command_bus.py
```

Expected: pass.

---

## Task 5 — Conversation Command Bridge

**Files:**

- Create: `backend/src/fitmas/legacy/conversation_command_bridge.py`
- Create: `tests/test_conversation_command_bridge.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`

- [ ] **Step 1: Write bridge tests**

Create `tests/test_conversation_command_bridge.py`:

```python
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-command-bridge-", suffix=".db"))

from fitmas import schema as s
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.legacy.conversation_command_bridge import apply_coach_decision_commands, apply_turn_plan_memory_commands
from fitmas.llm import AvailabilityConstraintAction, CoachDecision


class ConversationCommandBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(name="Loic", timezone="Europe/Paris")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()

    def test_apply_coach_decision_commands_returns_legacy_metric_payload_and_writes(self) -> None:
        writes: list[dict] = []
        decision = CoachDecision(
            response_type="reply",
            rationale="bridge should preserve legacy action metrics",
            fitmas_message="ok",
            memory_actions=(
                AvailabilityConstraintAction(
                    type="record_availability",
                    window_text="piscine fermee",
                    availability="unavailable",
                    sport_type="swimming",
                    starts_on="2026-05-14",
                    ends_on="2026-05-28",
                    confidence=0.9,
                    evidence="piscine fermee",
                ),
            ),
        )

        metrics = apply_coach_decision_commands(
            db=self.db,
            user=self.user,
            decision=decision,
            turn_memory_writes=writes,
            unresolved_execution_followup=None,
            turn_plan=None,
            canonical_understanding=None,
        )

        self.assertEqual(metrics["memory_applied"], 1)
        self.assertEqual(metrics["execution_applied"], 0)
        self.assertEqual(writes[0]["category"], "availability")
        self.assertEqual(writes[0]["source"], "coach_decision")
        self.assertEqual(writes[0]["action"], "applied")

    def test_apply_turn_plan_memory_commands_uses_command_bus(self) -> None:
        writes: list[dict] = []
        turn_context: dict[str, object] = {}
        turn_plan = SimpleNamespace(
            availability_constraint={
                "availability": "unavailable",
                "sport_type": "swimming",
                "scope": "sport",
                "starts_on": "2026-05-14",
                "ends_on": "2026-05-28",
            },
            confidence=0.8,
        )

        apply_turn_plan_memory_commands(
            db=self.db,
            user=self.user,
            turn_plan=turn_plan,
            turn_memory_writes=writes,
            turn_context=turn_context,
        )

        self.assertEqual(writes[0]["category"], "availability")
        self.assertEqual(writes[0]["source"], "turn_plan")
        self.assertEqual(turn_context["turn_plan_memory_action_result"]["memory_applied"], 1)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_command_bridge.py
```

Expected: failure because `legacy/conversation_command_bridge.py` does not exist.

- [ ] **Step 3: Implement bridge application functions**

Create `backend/src/fitmas/legacy/conversation_command_bridge.py`:

```python
from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.decision import CoachUnderstanding, CommandResult
from fitmas.legacy.coach_command_adapter import (
    CoachCommandBundle,
    commands_from_legacy_decision,
    commands_from_understanding,
)
from fitmas.legacy.conversation_command_bus import ConversationCommandBus


logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger("fitmas.metrics")


def commands_from_understanding_enabled() -> bool:
    return os.getenv("FITMAS_COMMANDS_FROM_UNDERSTANDING", "").strip().lower() in {"1", "true", "yes", "on"}


def apply_coach_decision_commands(
    *,
    db: Session,
    user: s.User,
    decision: Any,
    turn_memory_writes: list[dict],
    unresolved_execution_followup: str | None = None,
    turn_plan: Any | None = None,
    canonical_understanding: CoachUnderstanding | None = None,
    conversation_turn_id: int | None = None,
) -> dict[str, Any]:
    bundle = _command_bundle(
        decision=decision,
        turn_plan=turn_plan,
        canonical_understanding=canonical_understanding,
    )
    bus = ConversationCommandBus(
        db=db,
        user=user,
        source=bundle.source,
        conversation_turn_id=conversation_turn_id,
    )
    results = bus.apply(bundle.commands)
    turn_memory_writes.extend(_turn_memory_writes_from_results(results, source=bundle.source))
    if bundle.deferred_execution_count:
        turn_memory_writes.append(
            {
                "category": "execution",
                "key": "record_execution_update",
                "value": f"deferred={bundle.deferred_execution_count}",
                "source": bundle.source,
                "action": "deferred",
            }
        )
    metrics = _metric_payload(results, deferred_execution_count=bundle.deferred_execution_count)
    _log_metrics(
        user=user,
        bundle=bundle,
        metrics=metrics,
        unresolved_execution_followup=unresolved_execution_followup,
        pending_resolution=getattr(decision, "pending_resolution", None),
    )
    return metrics
```

- [ ] **Step 4: Implement turn-plan path and metrics helpers**

Add:

```python
def apply_turn_plan_memory_commands(
    *,
    db: Session,
    user: s.User,
    turn_plan: Any,
    turn_memory_writes: list[dict],
    turn_context: dict[str, object],
) -> None:
    bundle = commands_from_legacy_decision(_EmptyDecision(), turn_plan=turn_plan)
    if not bundle.commands:
        return
    bus = ConversationCommandBus(db=db, user=user, source="turn_plan")
    results = bus.apply(tuple(command for command in bundle.commands if command.domain == "memory"))
    turn_memory_writes.extend(_turn_memory_writes_from_results(results, source="turn_plan"))
    metrics = _metric_payload(results, deferred_execution_count=0)
    turn_context["turn_plan_memory_action_result"] = {
        "memory_applied": metrics["memory_applied"],
        "memory_blocked": metrics["memory_blocked"],
        "saved_keys": [
            key
            for result in results
            for key in tuple(result.payload.get("saved_keys", ()) or ())
        ],
    }


class _EmptyDecision:
    memory_actions = ()
    execution_actions = ()
    response_type = "reply"
    plan_patch = None
    pending_resolution = None
```

Add:

```python
def _command_bundle(
    *,
    decision: Any,
    turn_plan: Any | None,
    canonical_understanding: CoachUnderstanding | None,
) -> CoachCommandBundle:
    if commands_from_understanding_enabled() and canonical_understanding is not None:
        bundle = commands_from_understanding(canonical_understanding)
        if bundle.commands:
            return bundle
        logger.info("canonical_understanding_commands_empty falling_back_to_legacy_decision")
    return commands_from_legacy_decision(decision, turn_plan=turn_plan)


def _turn_memory_writes_from_results(results: tuple[CommandResult, ...], *, source: str) -> tuple[dict, ...]:
    writes: list[dict] = []
    for result in results:
        if result.domain == "memory":
            for saved_key in tuple(result.payload.get("saved_keys", ()) or ()):
                category, _, item_key = str(saved_key).partition(":")
                writes.append(
                    {
                        "category": category or "memory",
                        "key": item_key or str(saved_key),
                        "source": source,
                        "action": result.status,
                    }
                )
        elif result.domain == "execution":
            for session_id in tuple(result.payload.get("updated_session_ids", ()) or ()):
                writes.append(
                    {
                        "category": "execution",
                        "key": "record_execution_update",
                        "value": f"session_id={session_id}",
                        "source": source,
                        "action": result.status,
                    }
                )
            if result.status == "blocked":
                writes.append(
                    {
                        "category": "execution",
                        "key": "record_execution_update",
                        "value": "blocked=1",
                        "source": source,
                        "action": "blocked",
                    }
                )
    return tuple(writes)


def _metric_payload(results: tuple[CommandResult, ...], *, deferred_execution_count: int) -> dict[str, Any]:
    execution_updated_session_ids = tuple(
        session_id
        for result in results
        if result.domain == "execution"
        for session_id in tuple(result.payload.get("updated_session_ids", ()) or ())
    )
    return {
        "memory_applied": sum(int(result.payload.get("applied_count") or 0) for result in results if result.domain == "memory"),
        "memory_blocked": sum(int(result.payload.get("blocked_count") or 0) for result in results if result.domain == "memory"),
        "execution_applied": sum(int(result.payload.get("applied_count") or 0) for result in results if result.domain == "execution"),
        "execution_blocked": sum(int(result.payload.get("blocked_count") or 0) for result in results if result.domain == "execution"),
        "execution_deferred": deferred_execution_count,
        "execution_updated_session_ids": execution_updated_session_ids,
    }


def _log_metrics(
    *,
    user: s.User,
    bundle: CoachCommandBundle,
    metrics: dict[str, Any],
    unresolved_execution_followup: str | None,
    pending_resolution: Any,
) -> None:
    memory_count = sum(1 for command in bundle.commands if command.domain == "memory")
    execution_count = sum(1 for command in bundle.commands if command.domain == "execution")
    missing_execution_action = bool(unresolved_execution_followup and execution_count == 0)
    metrics_logger.info(
        "conversation_action_metrics user=%s memory_actions_per_turn=%s execution_actions_per_turn=%s pending_resolution_per_turn=%s llm_understanding_missing_action=%s memory_applied=%s execution_applied=%s command_source=%s",
        getattr(user, "id", None),
        memory_count,
        execution_count,
        1 if pending_resolution is not None else 0,
        1 if missing_execution_action else 0,
        metrics["memory_applied"],
        metrics["execution_applied"],
        bundle.source,
    )
```

- [ ] **Step 5: Wire `conversation_pipeline.py`**

Modify imports:

```python
from fitmas.legacy import conversation_command_bridge
```

Remove imports:

```python
from fitmas.execution_mutation_service import apply_execution_actions_for_user
from fitmas.memory_mutation_service import apply_memory_actions_for_user
```

Replace `_apply_turn_plan_memory_actions(...)` call with:

```python
conversation_command_bridge.apply_turn_plan_memory_commands(
    db=db,
    user=user,
    turn_plan=turn_plan,
    turn_memory_writes=turn_memory_writes,
    turn_context=turn_context,
)
```

Replace `_apply_coach_decision_actions(...)` body with:

```python
return conversation_command_bridge.apply_coach_decision_commands(
    db=db,
    user=user,
    decision=decision,
    turn_memory_writes=turn_memory_writes,
    unresolved_execution_followup=unresolved_execution_followup,
    turn_plan=turn_plan,
    canonical_understanding=turn_context.get("canonical_understanding") if isinstance(turn_context, dict) else None,
)
```

Delete these helpers from `conversation_pipeline.py` after moving them to the adapter:

```text
_memory_actions_with_turn_plan_availability
_availability_actions_match
_defer_conflicting_execution_actions
_has_availability_memory_action
_plan_patch_session_ids
_apply_turn_plan_memory_actions
_availability_memory_action_from_turn_plan
_clean_enum_value
_clean_optional_artifact_value
_availability_window_text
```

Keep `_normalized_pending_value` in `conversation_pipeline.py` if pending helpers still call it. If it is no longer used after the command adapter move, delete it.

- [ ] **Step 6: Run bridge and architecture tests**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_command_bridge.py tests/test_phase8f_command_extraction_architecture.py
```

Expected: pass.

---

## Task 6 — Understanding Signal Payload Contract

**Files:**

- Modify: `backend/src/fitmas/llm/prompts/understanding.py`
- Modify: `tests/test_llm_prompts_understanding.py`

- [ ] **Step 1: Add prompt test for signal payloads**

In `tests/test_llm_prompts_understanding.py`, add:

```python
def test_understanding_prompt_documents_command_payload_fields_without_commands() -> None:
    rendered = build_understanding_prompt(
        UnderstandingPromptInput(
            event_summary="message: je ne peux pas nager deux semaines",
            context_blocks=("plan compact",),
        )
    )

    text = rendered.system + "\n" + rendered.prompt

    assert "payload" in text
    assert "action_type" in text
    assert "record_availability" in text
    assert "record_health_signal" in text
    assert "record_execution_update" in text
    assert "commande DB" in text
    assert "Command" not in text
    assert "PlanPatch" not in text
```

- [ ] **Step 2: Run prompt test and verify failure**

Run:

```bash
./scripts/test-backend -q tests/test_llm_prompts_understanding.py
```

Expected: failure because payload fields are not documented.

- [ ] **Step 3: Extend the prompt schema**

In `backend/src/fitmas/llm/prompts/understanding.py`, change the `extracted_signals` schema entry to include payload:

```python
"extracted_signals": [
    {
        "type": "health | availability | preference | execution | readiness | planning | pending | other",
        "label": "short typed label",
        "status": "new | update | correction",
        "severity": "low | medium | high | unknown",
        "confidence": "0..1",
        "evidence": "user-provided evidence only",
        "payload": {
            "action_type": "record_health_signal | record_availability | record_preference | record_execution_update | null",
            "health_signal": "health signal label when action_type=record_health_signal",
            "body_area": "body area or null",
            "availability": "available | unavailable | limited | unknown",
            "window_text": "availability window in user words",
            "sport_type": "running | cycling | swimming | strength | null",
            "scope": "sport | day | week | general | null",
            "starts_on": "YYYY-MM-DD or null",
            "ends_on": "YYYY-MM-DD or null",
            "preference": "preference text when action_type=record_preference",
            "polarity": "prefer | avoid",
            "target_ref": "typed execution target reference or null",
            "target_session_id": "integer id or null",
            "completed": "true | false | null",
            "status": "completed | not_completed | unknown",
        },
    }
],
```

Keep this system rule unchanged:

```text
Tu ne produis pas de patch planning, ancienne mutation, commande DB ou write.
```

The payload is an interpretation artifact, not authorization to write.

- [ ] **Step 4: Run prompt tests**

Run:

```bash
./scripts/test-backend -q tests/test_llm_prompts_understanding.py tests/test_llm_understanding_service.py tests/test_coach_command_adapter.py
```

Expected: pass.

---

## Task 7 — Core Flow and Cutover Tests

**Files:**

- Modify: `tests/test_core_flows.py`
- Modify: `tests/test_conversation_debug_endpoint.py`

- [ ] **Step 1: Add a core flow assertion that memory/execution command bus preserves behavior**

In the existing core flow that records memory or execution updates, assert the debug payload still includes action metrics:

```python
assert response_json["debug"]["action_metrics"]["memory_applied"] >= 0
assert response_json["debug"]["action_metrics"]["execution_applied"] >= 0
```

If the exact test object uses a different variable name, keep the same existing fixture and add only the two assertions above.

- [ ] **Step 2: Add debug endpoint assertion for command source**

In `tests/test_conversation_debug_endpoint.py`, add an assertion to the existing conversation debug test:

```python
assert "command_source" in trace["metrics"]["conversation_action_metrics"][-1]
```

If the debug trace stores metric payloads under a different nested key, assert against that existing key. Do not change the debug endpoint shape only to satisfy this test.

- [ ] **Step 3: Run targeted flow tests**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py tests/test_conversation_debug_endpoint.py
```

Expected: pass.

---

## Task 8 — Docs and Kill List Update

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Update `docs/DECISION-RUNTIME-REFACTOR.md`**

Add a Phase 8F delivered section:

```markdown
## Livres en Phase 8F

Phase 8F extrait les writes memoire/execution de l'orchestrateur conversation.

- `conversation_pipeline.py` ne call plus directement `apply_memory_actions_for_user`.
- `conversation_pipeline.py` ne call plus directement `apply_execution_actions_for_user`.
- `legacy/coach_command_adapter.py` convertit les artefacts types en `Command`.
- `legacy/conversation_command_bus.py` applique les commandes via les services existants.
- `CommandResult` reference un event persiste quand une commande est appliquee.
- `FITMAS_COMMANDS_FROM_UNDERSTANDING` prepare la compilation depuis `CoachUnderstanding`, off par defaut.

Dette restante :

- `CoachDecision` reste le contrat provider legacy.
- `pending_resolution` reste porte par `CoachDecision`.
- les services root memoire/execution seront deplaces vers `domain/*` dans une phase ulterieure.
```

- [ ] **Step 2: Update `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`**

Add Phase 8F status:

```markdown
Phase 8F extrait les actions memoire/execution :

- les writes memoire/execution conversation passent par `ConversationCommandBus` ;
- `conversation_pipeline.py` ne possede plus ces writes ;
- `CoachDecision.memory_actions` et `CoachDecision.execution_actions` sont provider-compat, plus application directe ;
- `pending_resolution` reste legacy actif et devient le prochain chantier de suppression.
```

Update remaining legacy table row for `CoachDecision`:

```text
CoachDecision reste actif pour provider compat et pending_resolution.
memory_actions/execution_actions ne sont plus une route de write directe depuis conversation_pipeline.py.
```

- [ ] **Step 3: Update `docs/BUILD-ORDER.md`**

Add Phase 8F local status after verification:

```markdown
- Phase 8F livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-8f-command-extraction.md` ;
  - `legacy/coach_command_adapter.py` compile les actions types en `Command` ;
  - `legacy/conversation_command_bus.py` applique memoire/execution via les services existants ;
  - `conversation_pipeline.py` ne call plus directement les writers memoire/execution ;
  - `CommandResult` applique reference un event persiste ;
  - `FITMAS_COMMANDS_FROM_UNDERSTANDING` est off par defaut ;
  - dette restante : `pending_resolution` et provider `CoachDecision`.
```

- [ ] **Step 4: Update `docs/README.md`**

Add the 8F plan to the relevant Decision Runtime plan list:

```markdown
- `superpowers/plans/2026-05-14-decision-runtime-phase-8f-command-extraction.md` — plan Phase 8F pour extraire les writes memoire/execution vers CommandBus.
```

- [ ] **Step 5: Run docs list**

Run:

```bash
./scripts/docs:list
```

Expected: the new 8F plan appears with summary and `read_when`.

---

## Task 9 — Final Verification

**Files:**

- No new files.

- [ ] **Step 1: Run targeted 8F tests**

Run:

```bash
./scripts/test-backend -q \
  tests/test_phase8f_command_extraction_architecture.py \
  tests/test_memory_mutation_service.py \
  tests/test_coach_command_adapter.py \
  tests/test_conversation_command_bus.py \
  tests/test_conversation_command_bridge.py \
  tests/test_llm_prompts_understanding.py \
  tests/test_llm_understanding_service.py
```

Expected: pass.

- [ ] **Step 2: Run architecture regression pack**

Run:

```bash
./scripts/test-backend -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8b_cutover_architecture.py \
  tests/test_phase8c_legacy_kill_architecture.py \
  tests/test_phase8d_bridge_shrink_architecture.py \
  tests/test_phase8e_understanding_cutover_architecture.py \
  tests/test_phase8f_command_extraction_architecture.py
```

Expected: pass.

- [ ] **Step 3: Run full backend suite**

Run:

```bash
./scripts/test-backend -q
```

Expected: pass.

- [ ] **Step 4: Run command-related real smoke**

Run:

```bash
FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1 ./scripts/smoke-real-conversations --scenario heartbeat_non_completion
```

Expected:

```text
exit 0
logs include decision_runtime.canonical_understanding
execution update still writes through command bus path
```

Run:

```bash
./scripts/smoke-decision-runtime-cutover
```

Expected:

```text
RESULT: OK
```

If provider latency stalls, record the exact stage and keep unit/architecture evidence separate from provider evidence.

---

## Acceptance Criteria

8F is complete only if all are true:

```text
1. conversation_pipeline.py has no direct import of memory_mutation_service.
2. conversation_pipeline.py has no direct import of execution_mutation_service.
3. Existing memory/execution behavior is preserved through ConversationCommandBus.
4. Applied CommandResult objects reference persisted event ids.
5. Turn-plan availability writes use the command bridge.
6. Canonical Understanding signal command compilation exists behind FITMAS_COMMANDS_FROM_UNDERSTANDING.
7. The canonical command flag is off by default.
8. decision/ imports no legacy/write/runtime code.
9. Full backend suite passes.
10. Docs explicitly state pending_resolution remains legacy for 8G.
```

## What 8F Leaves For 8G

```text
1. pending_resolution extraction/removal.
2. Final provider cutover away from CoachDecision.
3. Deleting llm/decision_legacy.py.
4. Removing conversation_prompt_modules.py action schema.
5. Moving memory/execution root services into domain/memory and domain/execution.
6. Making canonical Understanding commands default after dogfood parity.
```

## Review Checklist

Ask these questions before accepting the implementation:

```text
Did any code parse free user text?
Did conversation_pipeline.py gain a new branch?
Did any action write bypass ConversationCommandBus?
Did a CommandResult claim applied without an event id?
Did canonical Understanding commands become default by accident?
Did decision/ import legacy?
Did pending_resolution behavior change outside this scope?
Did docs mark the remaining legacy clearly?
```

## Execution Order

```text
8F1 architecture gates
8F2 event ids in mutation service results
8F3 coach command adapter
8F4 conversation command bus
8F5 conversation command bridge and pipeline wiring
8F6 understanding payload prompt contract
8F7 core flow tests
8F8 docs
8F9 verification
```

## Commit Plan

Use small commits:

```bash
git add tests/test_phase8f_command_extraction_architecture.py
git commit -m "test: add phase 8f command extraction gates"

git add backend/src/fitmas/memory_mutation_service.py backend/src/fitmas/execution_mutation_service.py tests/test_memory_mutation_service.py
git commit -m "feat: return event ids from action mutation services"

git add backend/src/fitmas/legacy/coach_command_adapter.py tests/test_coach_command_adapter.py
git commit -m "feat: map coach action artifacts to commands"

git add backend/src/fitmas/legacy/conversation_command_bus.py tests/test_conversation_command_bus.py
git commit -m "feat: apply conversation commands through command bus"

git add backend/src/fitmas/legacy/conversation_command_bridge.py backend/src/fitmas/conversation_pipeline.py tests/test_conversation_command_bridge.py
git commit -m "refactor: route conversation actions through command bridge"

git add backend/src/fitmas/llm/prompts/understanding.py tests/test_llm_prompts_understanding.py
git commit -m "feat: document understanding signal payloads"

git add docs/DECISION-RUNTIME-REFACTOR.md docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md docs/BUILD-ORDER.md docs/README.md
git commit -m "docs: record phase 8f command extraction"
```
