---
summary: implementation plan for Decision Runtime Phase 8D bridge shrink and runtime ownership
read_when:
  - implementing Decision Runtime Phase 8D
  - shrinking conversation_pipeline.py after Phase 8C
  - moving API message routes toward the target app/api organization
  - reducing final_reply, heartbeat and CoachDecision legacy bridge authority
---

# Decision Runtime Phase 8D Bridge Shrink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Decision Runtime own the orchestration shape while shrinking the remaining legacy bridges without reopening deleted 8C routes.

**Architecture:** Phase 8D is consolidation, not a rewrite. The new `decision/` runtime gets a concrete pure service shell; legacy-heavy conversation behavior is extracted into explicit `legacy/` bridges; API message routing moves toward `app/api/routes_messages.py`; heartbeat and tools legacy stay off active paths.

**Tech Stack:** Python 3.13, pytest architecture tests, existing FastAPI routes, SQLAlchemy session dependency, current `DecisionOutcome` / `DecisionReplyComposer` / `InputEvent` types, existing smoke scripts.

---

## CTO Decision

Do **not** delete `final_reply.py`, `llm/decision_legacy.py`, or `conversation_prompt_modules.py` in 8D.

8D should make the old code less powerful and easier to delete later:

```text
8D = runtime shell + file boundary cleanup + bridge shrink
8E = first real Understanding cutover slice
8F = final_reply backend retirement slice
```

The risk is not test volume. The risk is accidentally recreating a second runtime while moving code. Every task must preserve the rule:

```text
legacy/ may adapt old contracts.
decision/ must not import legacy/.
conversation_pipeline.py must not regain decision authority.
```

## Current Baseline

Phase 8C evidence:

```text
./scripts/test-backend -q -> 1116 passed, 11 skipped, 11 subtests passed
./scripts/smoke-decision-runtime-cutover -> RESULT: OK
```

Current line budget:

```text
conversation_pipeline.py            3831 lines
final_reply.py                      1167 lines
decision/runtime.py                   19 lines
legacy/final_reply_backend.py        130 lines
legacy/heartbeat_runtime_adapter.py  251 lines
```

## Non-Negotiables

```text
1. No deterministic parser over free user text.
2. No restored MutationDecision write path.
3. No restored direct PlanPatch branch in conversation_pipeline.py.
4. No direct fitmas.final_reply import outside allowed legacy bridges.
5. No draft_* or propose_replan in default tool registry.
6. No WeeklyPlan / DayPlan read in conversation, heartbeat, mutation or app cockpit runtime.
7. decision/ must not import fitmas.legacy, fitmas.final_reply, fitmas.llm.decision_legacy or conversation_pipeline.
8. Every extraction must be behavior-preserving and covered by tests before moving to the next slice.
```

## File Map

Create:

```text
backend/src/fitmas/app/api/__init__.py
backend/src/fitmas/app/api/routes_messages.py
backend/src/fitmas/legacy/conversation_planning_bridge.py
backend/src/fitmas/legacy/conversation_readonly_reply_bridge.py
backend/src/fitmas/legacy/conversation_decision_bridge.py
tests/test_decision_runtime_service.py
tests/test_phase8d_bridge_shrink_architecture.py
tests/test_app_api_routes_messages.py
```

Modify:

```text
backend/src/fitmas/decision/runtime.py
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/api_messages.py
backend/src/fitmas/api.py
backend/src/fitmas/legacy/__init__.py
docs/DECISION-RUNTIME-REFACTOR.md
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/BUILD-ORDER.md
docs/README.md
```

Do not modify unless a test proves it is needed:

```text
backend/src/fitmas/final_reply.py
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/tools/registry.py
backend/src/fitmas/plan_mutation_service.py
```

## Task 1 — 8D Architecture Gates

**Files:**

- Create: `tests/test_phase8d_bridge_shrink_architecture.py`

- [ ] **Step 1: Write failing architecture tests**

Create `tests/test_phase8d_bridge_shrink_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_8d_decision_runtime_service_exists_without_legacy_imports() -> None:
    source = _source("decision/runtime.py")

    assert "class DecisionRuntimeService" in source
    assert "fitmas.legacy" not in source
    assert "conversation_pipeline" not in source
    assert "fitmas.final_reply" not in source
    assert "decision_legacy" not in source


def test_8d_conversation_pipeline_stays_under_bridge_shrink_budget() -> None:
    line_count = len(_source("conversation_pipeline.py").splitlines())

    assert line_count <= 3600


def test_8d_message_route_lives_under_target_app_api_package() -> None:
    source = _source("app/api/routes_messages.py")

    assert "router = APIRouter()" in source
    assert "run_conversation_turn" in source
    assert "ConversationTurnInput" in source


def test_8d_root_api_messages_is_compat_wrapper_only() -> None:
    source = _source("api_messages.py")

    assert "from fitmas.app.api.routes_messages import" in source
    assert "def post_message(" not in source
    assert "router = APIRouter()" not in source


def test_8d_no_active_heartbeat_skill_imports_outside_legacy() -> None:
    offenders: list[str] = []
    allowed_prefixes = {
        "legacy/",
        "skills/heartbeat/",
    }
    for path in sorted(SRC.rglob("*.py")):
        relative = str(path.relative_to(SRC))
        if any(relative.startswith(prefix) for prefix in allowed_prefixes):
            continue
        imports = _imports(path)
        if any(module.startswith("fitmas.skills.heartbeat") for module in imports):
            offenders.append(relative)

    assert offenders == []


def test_8d_conversation_pipeline_uses_explicit_legacy_bridges() -> None:
    source = _source("conversation_pipeline.py")

    assert "conversation_planning_bridge" in source
    assert "conversation_readonly_reply_bridge" in source
    assert "conversation_decision_bridge" in source
    assert "legacy_decision_contract_disabled" in source
    assert 'response_type == "plan_patch"' not in source
    assert 'response_type == "requires_confirmation"' not in source
    assert 'response_type == "mutation_decision"' not in source
```

- [ ] **Step 2: Run the architecture tests and confirm they fail**

Run:

```bash
./scripts/test-backend -q tests/test_phase8d_bridge_shrink_architecture.py
```

Expected:

```text
FAIL test_8d_decision_runtime_service_exists_without_legacy_imports
FAIL test_8d_conversation_pipeline_stays_under_bridge_shrink_budget
FAIL test_8d_message_route_lives_under_target_app_api_package
```

- [ ] **Step 3: Keep the tests failing until the relevant task lands**

Do not weaken the tests. If a test fails because the exact line budget is too tight after legitimate extraction, use `3700` as the maximum once, document why in this plan, and keep the budget below the Phase 8C baseline of `3831`.

## Task 2 — Concrete Pure `DecisionRuntimeService`

**Files:**

- Modify: `backend/src/fitmas/decision/runtime.py`
- Create: `tests/test_decision_runtime_service.py`

- [ ] **Step 1: Write the service tests**

Create `tests/test_decision_runtime_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from fitmas.decision import (
    CoachUnderstanding,
    Command,
    CommandResult,
    DecisionExplanation,
    DecisionOutcome,
    InputEvent,
    ReplyContract,
)
from fitmas.decision.runtime import DecisionRuntimeService


def _event() -> InputEvent:
    return InputEvent(
        id="evt_1",
        user_id=1,
        source="telegram",
        type="user_message",
        text="deplace demain",
        payload={},
        occurred_at=None,
    )


def _understanding() -> CoachUnderstanding:
    return CoachUnderstanding(intent="plan_lookup", confidence=0.9, user_summary="lookup")


def _outcome() -> DecisionOutcome:
    return DecisionOutcome(
        kind="answer",
        commands=(
            Command(
                id="cmd_1",
                domain="memory",
                name="record_note",
                payload={"summary": "note"},
            ),
        ),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label="Reponse",
            reason_summary="Plan lu.",
            evidence=("runtime_service",),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="answer",
            audience="conversation",
            allowed_claims=("answer",),
            forbidden_claims=("plan_committed_without_event",),
        ),
    )


@dataclass
class SpyContextBuilder:
    calls: list[str]

    def build(self, event):
        self.calls.append(f"context:{event.id}")
        return {"context": True}


@dataclass
class SpyUnderstandingService:
    calls: list[str]

    def understand(self, event, context):
        self.calls.append(f"understand:{event.id}:{bool(context)}")
        return _understanding()


@dataclass
class SpyDecisionEngine:
    calls: list[str]

    def decide(self, event, context, understanding):
        self.calls.append(f"decide:{event.id}:{understanding.intent}")
        return _outcome()


@dataclass
class SpyCommandBus:
    calls: list[str]

    def apply(self, commands):
        self.calls.append(f"commands:{len(commands)}")
        return (
            CommandResult(
                command_id="cmd_1",
                domain="memory",
                name="record_note",
                status="applied",
                event_id="mem_evt_1",
                payload={"summary": "note saved"},
            ),
        )


@dataclass
class SpyReplyComposer:
    calls: list[str]

    def compose(self, outcome, context, event):
        self.calls.append(f"reply:{outcome.kind}:{len(outcome.applied_commands)}")
        return "Plan lu."


def test_runtime_service_runs_context_understanding_decision_commands_reply_in_order() -> None:
    calls: list[str] = []
    service = DecisionRuntimeService(
        context_builder=SpyContextBuilder(calls),
        understanding_service=SpyUnderstandingService(calls),
        decision_engine=SpyDecisionEngine(calls),
        command_bus=SpyCommandBus(calls),
        reply_composer=SpyReplyComposer(calls),
    )

    result = service.run(_event())

    assert result.reply_text == "Plan lu."
    assert result.outcome.applied_commands[0].event_id == "mem_evt_1"
    assert calls == [
        "context:evt_1",
        "understand:evt_1:True",
        "decide:evt_1:plan_lookup",
        "commands:1",
        "reply:answer:1",
    ]


def test_runtime_service_skips_command_bus_when_outcome_has_no_commands() -> None:
    calls: list[str] = []

    class NoCommandEngine(SpyDecisionEngine):
        def decide(self, event, context, understanding):
            outcome = _outcome()
            return DecisionOutcome(
                kind=outcome.kind,
                commands=(),
                applied_commands=(),
                candidates=outcome.candidates,
                selected_candidate_id=outcome.selected_candidate_id,
                explanation=outcome.explanation,
                reply_contract=outcome.reply_contract,
            )

    service = DecisionRuntimeService(
        context_builder=SpyContextBuilder(calls),
        understanding_service=SpyUnderstandingService(calls),
        decision_engine=NoCommandEngine(calls),
        command_bus=SpyCommandBus(calls),
        reply_composer=SpyReplyComposer(calls),
    )

    result = service.run(_event())

    assert result.reply_text == "Plan lu."
    assert "commands:0" not in calls
```

- [ ] **Step 2: Run the tests and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_decision_runtime_service.py::test_runtime_service_runs_context_understanding_decision_commands_reply_in_order
```

Expected:

```text
ImportError: cannot import name 'DecisionRuntimeService'
```

- [ ] **Step 3: Implement the minimal pure service**

Modify `backend/src/fitmas/decision/runtime.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol, Sequence

from .input_event import InputEvent
from .outcome import Command, CommandResult, DecisionOutcome
from .understanding import CoachUnderstanding


@dataclass(frozen=True, slots=True)
class DecisionResult:
    event: InputEvent
    outcome: DecisionOutcome
    reply_text: str


class DecisionRuntime(Protocol):
    def run(self, event: InputEvent) -> DecisionResult:
        ...


class RuntimeContextBuilder(Protocol):
    def build(self, event: InputEvent) -> Any:
        ...


class RuntimeUnderstandingService(Protocol):
    def understand(self, event: InputEvent, context: Any) -> CoachUnderstanding:
        ...


class RuntimeDecisionEngine(Protocol):
    def decide(self, event: InputEvent, context: Any, understanding: CoachUnderstanding) -> DecisionOutcome:
        ...


class RuntimeCommandBus(Protocol):
    def apply(self, commands: Sequence[Command]) -> tuple[CommandResult, ...]:
        ...


class RuntimeReplyComposer(Protocol):
    def compose(self, outcome: DecisionOutcome, context: Any, event: InputEvent) -> str:
        ...


@dataclass(frozen=True, slots=True)
class DecisionRuntimeService:
    context_builder: RuntimeContextBuilder
    understanding_service: RuntimeUnderstandingService
    decision_engine: RuntimeDecisionEngine
    command_bus: RuntimeCommandBus
    reply_composer: RuntimeReplyComposer

    def run(self, event: InputEvent) -> DecisionResult:
        context = self.context_builder.build(event)
        understanding = self.understanding_service.understand(event, context)
        outcome = self.decision_engine.decide(event, context, understanding)
        if outcome.commands:
            applied_commands = self.command_bus.apply(outcome.commands)
            outcome = replace(outcome, applied_commands=applied_commands)
        reply_text = self.reply_composer.compose(outcome, context, event)
        return DecisionResult(event=event, outcome=outcome, reply_text=reply_text)
```

- [ ] **Step 4: Run tests**

Run:

```bash
./scripts/test-backend -q tests/test_decision_runtime_service.py tests/test_decision_runtime_architecture.py
```

Expected:

```text
PASS
```

## Task 3 — Move Message Route To Target `app/api` Package

**Files:**

- Create: `backend/src/fitmas/app/api/__init__.py`
- Create: `backend/src/fitmas/app/api/routes_messages.py`
- Modify: `backend/src/fitmas/api_messages.py`
- Modify: `backend/src/fitmas/api.py`
- Create: `tests/test_app_api_routes_messages.py`

- [ ] **Step 1: Write tests for route compatibility**

Create `tests/test_app_api_routes_messages.py`:

```python
from __future__ import annotations


def test_api_messages_exports_target_router() -> None:
    import fitmas.api_messages as legacy_module
    from fitmas.app.api import routes_messages

    assert legacy_module.router is routes_messages.router
    assert legacy_module.post_message is routes_messages.post_message


def test_routes_messages_keeps_post_endpoint_registered() -> None:
    from fitmas.app.api.routes_messages import router

    routes = {(route.path, tuple(sorted(route.methods))) for route in router.routes}

    assert ("/api/v0/messages", ("POST",)) in routes
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_app_api_routes_messages.py
```

Expected:

```text
ModuleNotFoundError: No module named 'fitmas.app.api'
```

- [ ] **Step 3: Create `app/api` package**

Create `backend/src/fitmas/app/api/__init__.py`:

```python
from __future__ import annotations
```

- [ ] **Step 4: Move route implementation**

Move all current code from `backend/src/fitmas/api_messages.py` into
`backend/src/fitmas/app/api/routes_messages.py`.

Keep imports identical except local module path comments. The route function must still call:

```python
from fitmas.conversation_pipeline import run_conversation_turn
```

inside `post_message()` to avoid import-time circularity.

- [ ] **Step 5: Replace root module with compat exports**

Replace `backend/src/fitmas/api_messages.py` with:

```python
from __future__ import annotations

from fitmas.app.api.routes_messages import (
    _active_memory_payloads,
    _coerce_local_date,
    _latest_agent_text,
    _persist_memory_updates,
    _resolve_day_updated,
    _targeted_execution_clarification,
    _value,
    _yesterday_session_covered_by_active_constraint,
    post_message,
    router,
)

__all__ = [
    "router",
    "post_message",
    "_resolve_day_updated",
    "_active_memory_payloads",
    "_persist_memory_updates",
    "_value",
    "_coerce_local_date",
    "_targeted_execution_clarification",
    "_yesterday_session_covered_by_active_constraint",
    "_latest_agent_text",
]
```

This keeps existing tests and monkeypatches working while moving the durable home.

- [ ] **Step 6: Update API import if needed**

Inspect `backend/src/fitmas/api.py`. If it imports `fitmas.api_messages`, leave it if all tests pass. If the architecture test expects target import, change only that import to:

```python
from fitmas.app.api.routes_messages import router as messages_router
```

Do not change route behavior.

- [ ] **Step 7: Run targeted tests**

Run:

```bash
./scripts/test-backend -q tests/test_app_api_routes_messages.py tests/test_core_flows.py tests/test_conversation_debug_endpoint.py
```

Expected:

```text
PASS
```

## Task 4 — Extract Planning Runtime Conversation Bridge

**Files:**

- Create: `backend/src/fitmas/legacy/conversation_planning_bridge.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_conversation_planning_runtime_adapter.py`
- Test: `tests/test_conversation_planning_runtime_reply_composer.py`
- Test: `tests/test_phase8b_planning_cutover.py`
- Test: `tests/test_phase8c_legacy_kill_architecture.py`

- [ ] **Step 1: Write or extend architecture test**

Extend `tests/test_phase8d_bridge_shrink_architecture.py`:

```python
def test_8d_planning_cutover_helpers_live_in_legacy_bridge() -> None:
    pipeline = _source("conversation_pipeline.py")
    bridge = _source("legacy/conversation_planning_bridge.py")

    assert "def maybe_handle_planning_runtime_cutover" not in pipeline
    assert "def maybe_handle_planning_runtime_cutover" in bridge
    assert "planning_runtime_unhandled" in bridge
    assert "legacy_decision_contract_disabled" in bridge
```

- [ ] **Step 2: Run architecture test and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_phase8d_bridge_shrink_architecture.py::test_8d_planning_cutover_helpers_live_in_legacy_bridge
```

Expected:

```text
FileNotFoundError or assertion failure
```

- [ ] **Step 3: Move planning bridge helpers**

Move these functions from `conversation_pipeline.py` to `legacy/conversation_planning_bridge.py`:

```text
_maybe_handle_planning_runtime_cutover -> maybe_handle_planning_runtime_cutover
_planning_runtime_unhandled_outcome -> planning_runtime_unhandled_outcome
_legacy_decision_contract_disabled_outcome -> legacy_decision_contract_disabled_outcome
_conversation_outcome_from_planning_runtime_result -> conversation_outcome_from_planning_runtime_result
_planning_runtime_response_mode -> planning_runtime_response_mode
```

The new module may import:

```python
from fitmas.decision import DecisionExplanation, DecisionOutcome, DecisionReplyComposer, ReplyContract
from fitmas.legacy.final_reply_backend import LegacyFinalReplyBackend
from fitmas.legacy.planning_outcome_adapter import planning_decision_to_outcome
from fitmas.legacy.planning_runtime_adapter import run_planning_runtime_attempt_from_legacy_decision
from fitmas.models import Extraction
from fitmas.conversation_contract import ConversationTurnOutcome
```

It must not import:

```text
fitmas.conversation_pipeline
fitmas.final_reply
```

- [ ] **Step 4: Inject dependencies explicitly**

In `conversation_planning_bridge.py`, make `maybe_handle_planning_runtime_cutover()` accept the pure callables it needs:

```python
def maybe_handle_planning_runtime_cutover(
    *,
    decision,
    state,
    conversation_context,
    coach_bundle,
    db,
    user,
    source_text: str,
    reviewer_request_json_fn,
    grounding_facts: tuple[str, ...],
    planning_context_from_turn_state_fn,
    decision_reply_composer_fn,
    compose_no_change_reply_for_turn_fn,
    turn_context: dict[str, object] | None = None,
    action_result: dict | None = None,
) -> ConversationTurnOutcome | None:
    ...
```

This avoids circular imports while keeping behavior identical.

- [ ] **Step 5: Update `conversation_pipeline.py` call sites**

Replace:

```python
outcome = _maybe_handle_planning_runtime_cutover(...)
```

with:

```python
outcome = conversation_planning_bridge.maybe_handle_planning_runtime_cutover(
    ...,
    planning_context_from_turn_state_fn=_planning_context_from_turn_state,
    decision_reply_composer_fn=_decision_reply_composer,
    compose_no_change_reply_for_turn_fn=_compose_no_change_reply_for_turn,
)
```

Replace:

```python
outcome = _legacy_decision_contract_disabled_outcome(...)
```

with:

```python
outcome = conversation_planning_bridge.legacy_decision_contract_disabled_outcome(
    ...,
    decision_reply_composer_fn=_decision_reply_composer,
)
```

- [ ] **Step 6: Preserve test imports temporarily**

Some tests may import private helpers from `conversation_pipeline.py`.
For 8D, either update tests to import `fitmas.legacy.conversation_planning_bridge`, or keep thin aliases in `conversation_pipeline.py`:

```python
_conversation_outcome_from_planning_runtime_result = (
    conversation_planning_bridge.conversation_outcome_from_planning_runtime_result
)
```

Use aliases only for tests that still need them. Do not keep aliases for `maybe_handle_planning_runtime_cutover`, because the goal is to shrink the active pipeline.

- [ ] **Step 7: Run targeted tests**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_planning_runtime_adapter.py tests/test_conversation_planning_runtime_reply_composer.py tests/test_phase8b_planning_cutover.py tests/test_phase8c_legacy_kill_architecture.py tests/test_phase8d_bridge_shrink_architecture.py
```

Expected:

```text
PASS
conversation_pipeline.py line count below 3600
```

## Task 5 — Extract Read-Only Reply Bridge

**Files:**

- Create: `backend/src/fitmas/legacy/conversation_readonly_reply_bridge.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_core_flows.py`
- Test: `tests/test_conversation_planning_runtime_reply_composer.py`

- [ ] **Step 1: Add architecture test**

Extend `tests/test_phase8d_bridge_shrink_architecture.py`:

```python
def test_8d_readonly_reply_helpers_live_in_legacy_bridge() -> None:
    pipeline = _source("conversation_pipeline.py")
    bridge = _source("legacy/conversation_readonly_reply_bridge.py")

    assert "def compose_no_change_reply_for_turn" in bridge
    assert "def _compose_no_change_reply_for_turn" not in pipeline
    assert "compose_plan_lookup_reply" in bridge
    assert "compose_execution_report_reply" in bridge
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_phase8d_bridge_shrink_architecture.py::test_8d_readonly_reply_helpers_live_in_legacy_bridge
```

Expected:

```text
FAIL
```

- [ ] **Step 3: Move read-only reply helpers**

Move from `conversation_pipeline.py` to `legacy/conversation_readonly_reply_bridge.py`:

```text
_compose_no_change_reply_for_turn -> compose_no_change_reply_for_turn
_memory_action_phrases_for_final_reply -> memory_action_phrases_for_final_reply
_execution_action_phrases_for_final_reply -> execution_action_phrases_for_final_reply
_turn_context_primary_intent -> turn_context_primary_intent
_turn_context_requires_truth_read -> turn_context_requires_truth_read
_turn_context_should_ground_plan_lookup -> turn_context_should_ground_plan_lookup
```

The new module may import:

```python
from sqlalchemy.orm import Session
from fitmas import repository as repo
from fitmas.grounding_contract import ReplyGroundingPacket
from fitmas.legacy import conversation_reply_adapter as final_reply
```

- [ ] **Step 4: Update call sites**

Replace calls in `conversation_pipeline.py`:

```python
_compose_no_change_reply_for_turn(...)
```

with:

```python
conversation_readonly_reply_bridge.compose_no_change_reply_for_turn(...)
```

Replace calls to moved helper predicates with bridge calls or local aliases.

- [ ] **Step 5: Keep monkeypatch compatibility**

Existing tests monkeypatch:

```python
conversation_pipeline.final_reply.compose_no_change_reply
```

Do not remove:

```python
from fitmas.legacy import conversation_reply_adapter as final_reply
```

from `conversation_pipeline.py` in this task. That removal belongs in a later phase after test and route callers patch the bridge directly.

- [ ] **Step 6: Run targeted tests**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py tests/test_conversation_planning_runtime_reply_composer.py tests/test_phase8d_bridge_shrink_architecture.py
```

Expected:

```text
PASS
conversation_pipeline.py line count below 3500 preferred, hard cap 3600
```

## Task 6 — Extract Legacy Decision Handling Bridge

**Files:**

- Create: `backend/src/fitmas/legacy/conversation_decision_bridge.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Test: `tests/test_core_flows.py`
- Test: `tests/test_phase8c_legacy_kill_architecture.py`
- Test: `tests/test_phase8d_bridge_shrink_architecture.py`

- [ ] **Step 1: Add architecture test**

Extend `tests/test_phase8d_bridge_shrink_architecture.py`:

```python
def test_8d_legacy_decision_helpers_live_in_legacy_bridge() -> None:
    pipeline = _source("conversation_pipeline.py")
    bridge = _source("legacy/conversation_decision_bridge.py")

    assert "def is_coach_decision" in bridge
    assert "def is_legacy_readonly_decision" in bridge
    assert "def coach_decision_payload" in bridge
    assert "def _is_coach_decision" not in pipeline
    assert "def _is_legacy_readonly_decision" not in pipeline
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
./scripts/test-backend -q tests/test_phase8d_bridge_shrink_architecture.py::test_8d_legacy_decision_helpers_live_in_legacy_bridge
```

Expected:

```text
FAIL
```

- [ ] **Step 3: Move decision shape helpers**

Move from `conversation_pipeline.py` to `legacy/conversation_decision_bridge.py`:

```text
_is_coach_decision -> is_coach_decision
_is_legacy_readonly_decision -> is_legacy_readonly_decision
_legacy_readonly_decision_payload -> legacy_readonly_decision_payload
_coach_decision_payload -> coach_decision_payload
_decision_json_for_turn -> decision_json_for_turn
```

Implementation in the new file:

```python
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def is_coach_decision(value: Any) -> bool:
    return bool(value is not None and hasattr(value, "response_type") and hasattr(value, "fitmas_message"))


def is_legacy_readonly_decision(value: Any) -> bool:
    return bool(
        value is not None
        and not hasattr(value, "response_type")
        and str(getattr(value, "mutation_type", "") or "") == "no_change"
        and hasattr(value, "fitmas_message")
    )


def legacy_readonly_decision_payload(decision: Any) -> dict[str, Any]:
    if hasattr(decision, "model_dump"):
        return dict(decision.model_dump(mode="json"))
    return {
        "mutation_type": getattr(decision, "mutation_type", None),
        "rationale": getattr(decision, "rationale", None),
        "fitmas_message": getattr(decision, "fitmas_message", None),
    }


def coach_decision_payload(decision: Any) -> dict[str, Any]:
    if hasattr(decision, "model_dump"):
        return dict(decision.model_dump(mode="json"))
    return {
        "response_type": getattr(decision, "response_type", None),
        "rationale": getattr(decision, "rationale", None),
        "fitmas_message": getattr(decision, "fitmas_message", None),
    }


def decision_json_for_turn(decision: Any | None) -> str:
    if decision is None:
        return "{}"
    try:
        if hasattr(decision, "model_dump_json"):
            return str(decision.model_dump_json())
        if hasattr(decision, "model_dump"):
            return json.dumps(decision.model_dump(mode="json"), ensure_ascii=True, default=str)
        if isinstance(decision, dict):
            return json.dumps(decision, ensure_ascii=True, default=str)
    except Exception:
        logger.exception("conversation_decision_json_serialization_failed")
    return "{}"
```

- [ ] **Step 4: Update call sites**

In `conversation_pipeline.py`, replace:

```python
_is_coach_decision(decision)
_coach_decision_payload(decision)
_is_legacy_readonly_decision(decision)
_legacy_readonly_decision_payload(decision)
_decision_json_for_turn(decision)
```

with:

```python
conversation_decision_bridge.is_coach_decision(decision)
conversation_decision_bridge.coach_decision_payload(decision)
conversation_decision_bridge.is_legacy_readonly_decision(decision)
conversation_decision_bridge.legacy_readonly_decision_payload(decision)
conversation_decision_bridge.decision_json_for_turn(decision)
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py tests/test_phase8c_legacy_kill_architecture.py tests/test_phase8d_bridge_shrink_architecture.py
```

Expected:

```text
PASS
```

## Task 7 — Heartbeat Legacy Dead-Path Guard

**Files:**

- Modify: `tests/test_phase8d_bridge_shrink_architecture.py`
- Modify if needed: `backend/src/fitmas/api_debug.py`
- Modify if needed: `backend/src/fitmas/api_ops.py`
- Modify if needed: `backend/src/fitmas/telegram_commands.py`

- [ ] **Step 1: Add stricter heartbeat import test**

Add to `tests/test_phase8d_bridge_shrink_architecture.py`:

```python
def test_8d_active_heartbeat_entrypoints_import_runtime_adapter_not_skill_loop() -> None:
    checked = {
        "app/telegram/scheduler.py",
        "telegram_commands.py",
        "api_debug.py",
        "api_ops.py",
    }
    offenders: list[str] = []
    for relative in checked:
        source = _source(relative)
        if "fitmas.skills.heartbeat" in source or "from fitmas import heartbeat" in source:
            offenders.append(relative)
        if "run_heartbeat_trigger" not in source and relative != "api_debug.py":
            offenders.append(f"{relative}:missing_runtime_adapter")

    assert offenders == []
```

- [ ] **Step 2: Run test**

Run:

```bash
./scripts/test-backend -q tests/test_phase8d_bridge_shrink_architecture.py::test_8d_active_heartbeat_entrypoints_import_runtime_adapter_not_skill_loop
```

Expected:

```text
PASS or a precise offender list
```

- [ ] **Step 3: Fix only direct active imports if test fails**

If an active entrypoint imports `fitmas.skills.heartbeat`, replace it with:

```python
from fitmas.legacy.heartbeat_runtime_adapter import run_heartbeat_trigger
```

Do not delete `skills/heartbeat/*` in 8D.

- [ ] **Step 4: Run heartbeat tests**

Run:

```bash
./scripts/test-backend -q tests/test_heartbeat_runtime_adapter.py tests/test_telegram_scheduler_runtime_adapter.py tests/test_phase8b_heartbeat_cutover.py tests/test_telegram_commands.py tests/test_heartbeat_debug_endpoint.py
```

Expected:

```text
PASS
```

## Task 8 — Docs And Verification

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Update the refactor canon**

Add a `Livres en Phase 8D` section to `docs/DECISION-RUNTIME-REFACTOR.md` with:

```text
- DecisionRuntimeService exists as a pure orchestration shell.
- message route moved under app/api/routes_messages.py with api_messages.py as compat wrapper.
- planning runtime conversation helpers live in legacy/conversation_planning_bridge.py.
- no-change/read-only reply helpers live in legacy/conversation_readonly_reply_bridge.py.
- legacy decision shape helpers live in legacy/conversation_decision_bridge.py.
- conversation_pipeline.py is reduced below the 8D line budget.
```

- [ ] **Step 2: Update the kill list**

In `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`, add:

```text
Phase 8D did not delete final_reply.py or decision_legacy.py.
It moved remaining bridge authority into named legacy modules and created a pure runtime service shell.
```

- [ ] **Step 3: Update build order**

In `docs/BUILD-ORDER.md`, add Phase 8D status and evidence.

- [ ] **Step 4: Update docs README if needed**

Ensure `docs/README.md` still points new agents to:

```text
DECISION-RUNTIME-REFACTOR.md
DECISION-RUNTIME-LEGACY-KILL-LIST.md
BUILD-ORDER.md
```

- [ ] **Step 5: Run architecture gates**

Run:

```bash
./scripts/test-backend -q tests/test_decision_runtime_architecture.py tests/test_phase8a_legacy_audit.py tests/test_phase8b_cutover_architecture.py tests/test_phase8c_legacy_kill_architecture.py tests/test_phase8d_bridge_shrink_architecture.py
```

Expected:

```text
PASS
```

- [ ] **Step 6: Run targeted behavior gates**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py tests/test_app_api_routes_messages.py tests/test_conversation_planning_runtime_adapter.py tests/test_conversation_planning_runtime_reply_composer.py tests/test_heartbeat_runtime_adapter.py tests/test_telegram_scheduler_runtime_adapter.py
```

Expected:

```text
PASS
```

- [ ] **Step 7: Run full backend**

Run:

```bash
./scripts/test-backend -q
```

Expected:

```text
1116+ passed, 11 skipped, 11 subtests passed
```

- [ ] **Step 8: Run real cutover smoke**

Run:

```bash
./scripts/smoke-decision-runtime-cutover
```

Expected:

```text
RESULT: OK
```

## Acceptance Criteria

8D is complete only if all are true:

```text
1. DecisionRuntimeService exists and decision/runtime.py still has no legacy imports.
2. /api/v0/messages lives in app/api/routes_messages.py.
3. api_messages.py is a compatibility wrapper.
4. conversation_pipeline.py is below the 8D budget and has less bridge logic than 8C.
5. Planning cutover helpers live in legacy/conversation_planning_bridge.py.
6. Read-only reply helpers live in legacy/conversation_readonly_reply_bridge.py.
7. Legacy decision shape helpers live in legacy/conversation_decision_bridge.py.
8. No active heartbeat entrypoint imports the heartbeat skill loop directly.
9. No 8C architecture guard regresses.
10. Full backend and smoke cutover pass.
```

## What 8D Explicitly Does Not Do

```text
- It does not delete final_reply.py.
- It does not delete llm/decision_legacy.py.
- It does not cut over Understanding runtime fully.
- It does not remove PlanPatch from all legacy prompts.
- It does not touch Phase B progression / prescription.
- It does not change provider strategy.
```

## Suggested Execution Order

```text
8D1 architecture gates
8D2 pure DecisionRuntimeService
8D3 app/api routes_messages migration
8D4 planning bridge extraction
8D5 read-only reply bridge extraction
8D6 legacy decision bridge extraction
8D7 heartbeat dead-path guard
8D8 docs + full verification
```

## Expected Next Phase

If 8D lands cleanly, Phase 8E should be:

```text
Understanding cutover slice:
- introduce RuntimeUnderstandingService adapter;
- map CoachUnderstanding to DecisionEngine input directly;
- make CoachDecision provider compat one step farther away from conversation_pipeline.py.
```
