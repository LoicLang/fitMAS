---
summary: implementation plan for Decision Runtime Phase 8L decide authority shrink
read_when:
  - implementing Decision Runtime Phase 8L
  - refactoring decide() or CoachDecision runtime authority
  - reducing conversation_pipeline.py dependence on fitmas.llm.decide
  - preparing the final migration away from CoachDecision
---

# Decision Runtime Phase 8L Decide Authority Shrink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Turn `decide()` into an explicit legacy provider adapter for conversation, so `conversation_pipeline.py` no longer calls it or consumes `fitmas_message` directly.

**Architecture:** 8L does not delete `CoachDecision` and does not default-enable canonical planning. It removes runtime authority from the wrong layer by inserting a provider boundary, moving the heavy legacy call and visible reply fallback behind `fitmas.legacy` bridges, and adding architecture tests that prevent direct `decide()` consumption from returning to the pipeline.

**Tech Stack:** Python 3.13, pytest/unittest, dataclasses, existing FitMAS legacy bridges, existing smoke wrappers from 8K and 8J.

---

## CTO Decision

8L is the first real `decide()` strike, but it must not be a big-bang rewrite of
`backend/src/fitmas/llm/decision_legacy.py`.

Why:

```text
decision_legacy.py is still the provider compatibility layer for many tests,
prompt snapshots, tool-use repair paths and fallback semantics.
Deleting or splitting it before the runtime stops depending on its shape would
create a false cleanup and a high regression surface.
```

So the order is:

```text
8L: remove runtime authority from decide()
8M: split decision_legacy.py internals once the runtime only sees a provider result
```

8L success means:

```text
conversation_pipeline.py does not call dependencies.decide directly
conversation_pipeline.py does not import llm_runtime
conversation_pipeline.py does not read decision.fitmas_message directly
CoachDecision is consumed only through legacy bridges
canonical commands/pending defaults from 8K remain active
planning cutover remains opt-in
```

## Scope

8L includes:

```text
1. Add architecture gates for direct decide authority.
2. Create a legacy CoachDecision provider adapter.
3. Move the conversation decide call behind a legacy bridge.
4. Move CoachDecision visible fallback reply behind a legacy bridge.
5. Keep command, pending and planning consumers in their existing bridges.
6. Add trace metadata showing which layer consumed legacy authority.
7. Update docs with the new boundary.
8. Run 8K default smokes, 8J planning smokes and full backend tests.
```

8L does not include:

```text
1. Deleting CoachDecision.
2. Deleting fitmas.llm.decide compatibility exports.
3. Splitting every helper out of decision_legacy.py.
4. Default-enabling FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER.
5. Rewriting prompt_contracts.py or conversation_prompt_modules.py.
6. Adding deterministic parsing of user text.
7. Adding a new visible reply composer outside DecisionReplyComposer / legacy adapters.
```

## File Map

Create:

```text
backend/src/fitmas/legacy/coach_decision_provider.py
backend/src/fitmas/legacy/conversation_decide_bridge.py
backend/src/fitmas/legacy/conversation_coach_decision_reply_bridge.py
tests/test_coach_decision_provider.py
tests/test_conversation_decide_bridge.py
tests/test_conversation_coach_decision_reply_bridge.py
tests/test_phase8l_decide_authority_architecture.py
```

Modify:

```text
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/conversation_contract.py
docs/DECISION-RUNTIME-REFACTOR.md
docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md
docs/BUILD-ORDER.md
docs/README.md
```

Do not modify in 8L unless a test proves it is unavoidable:

```text
backend/src/fitmas/llm/decision_legacy.py
backend/src/fitmas/conversation_prompt_modules.py
backend/src/fitmas/prompt_contracts.py
backend/src/fitmas/domain/planning/*
backend/src/fitmas/decision/*
```

If a failure seems to require editing `decision_legacy.py`, classify it first:

```text
provider compatibility bug -> maybe 8L
prompt contract cleanup -> defer to 8M/8N
canonical planning behavior -> defer, planning cutover stays opt-in
```

## Invariants

```text
1. No regex/keyword heuristic on free user text.
2. No new write path outside command/planning services.
3. No direct `CoachDecision.fitmas_message` read in conversation_pipeline.py.
4. No direct `dependencies.decide(...)` call in conversation_pipeline.py.
5. No `fitmas.llm` import in conversation_pipeline.py.
6. `CoachDecision` can remain in tests and legacy modules only.
7. Commands from Understanding stay default-on.
8. Pending from Understanding stays default-on.
9. Canonical planning cutover stays default-off.
10. `decision/` remains pure and does not import legacy or llm.
```

## Task 1 - Add 8L Architecture Gates

**Files:**

- Create: `tests/test_phase8l_decide_authority_architecture.py`

- [x] **Step 1: Write failing architecture tests**

Create `tests/test_phase8l_decide_authority_architecture.py`:

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


def test_8l_conversation_pipeline_does_not_call_decide_directly() -> None:
    source = _source("conversation_pipeline.py")

    assert "dependencies.decide(" not in source
    assert "llm_runtime" not in source
    assert "conversation_decide_bridge.run_legacy_coach_decision" in source


def test_8l_conversation_pipeline_does_not_read_fitmas_message_directly() -> None:
    source = _source("conversation_pipeline.py")

    assert "decision.fitmas_message" not in source
    assert "conversation_coach_decision_reply_bridge.compose_coach_decision_reply" in source


def test_8l_legacy_provider_boundary_exists() -> None:
    provider = _source("legacy/coach_decision_provider.py")
    bridge = _source("legacy/conversation_decide_bridge.py")

    assert "class CoachDecisionRequest" in provider
    assert "class CoachDecisionResult" in provider
    assert "class LegacyCoachDecisionProvider" in provider
    assert "def run_legacy_coach_decision(" in bridge
    assert "clear_last_decide_none" in provider


def test_8l_decision_package_stays_pure() -> None:
    forbidden = {
        "fitmas.legacy",
        "fitmas.llm",
        "fitmas.conversation_pipeline",
        "fitmas.memory_mutation_service",
        "fitmas.execution_mutation_service",
        "fitmas.plan_mutation_service",
    }
    for path in (SRC / "decision").glob("*.py"):
        imports = _imports(f"decision/{path.name}")
        assert not forbidden.intersection(imports), f"{path.name}: {forbidden.intersection(imports)}"


def test_8l_planning_cutover_remains_default_off() -> None:
    source = _source("legacy/conversation_understanding_bridge.py")

    assert 'FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER", default=False' in source
```

- [x] **Step 2: Run the architecture test red**

Run:

```bash
./scripts/test-backend -q tests/test_phase8l_decide_authority_architecture.py
```

Expected:

```text
FAIL on missing provider/bridge and direct decide authority still present.
```

## Task 2 - Create Legacy CoachDecision Provider Adapter

**Files:**

- Create: `backend/src/fitmas/legacy/coach_decision_provider.py`
- Create: `tests/test_coach_decision_provider.py`

- [x] **Step 1: Write provider tests**

Create `tests/test_coach_decision_provider.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy.coach_decision_provider import (
    CoachDecisionRequest,
    LegacyCoachDecisionProvider,
)


def _request() -> CoachDecisionRequest:
    return CoachDecisionRequest(
        user_text="J'ai pas eu le temps hier",
        plan_summary="",
        timeline_summary="timeline",
        execution_summary="execution",
        temporal_summary="temporal",
        activity_claim_summary="claim",
        signal_summary="signal",
        conversation_history=[{"role": "user", "text": "avant"}],
        coach_context={"turn_primary_intent": "execution_report"},
        remembered_facts=[{"key": "health:knee"}],
        time_context={"today": "2026-05-15"},
        tool_context=SimpleNamespace(pipeline="conversation"),
    )


def test_provider_clears_decide_none_and_forwards_request() -> None:
    calls: list[tuple[str, object]] = []
    returned = SimpleNamespace(response_type="no_change", fitmas_message="ok")

    def clear() -> None:
        calls.append(("clear", None))

    def decide(*args, **kwargs):
        calls.append(("decide_args", args))
        calls.append(("decide_kwargs", kwargs))
        return returned

    provider = LegacyCoachDecisionProvider(decide_fn=decide, clear_fn=clear)

    result = provider.decide(_request())

    assert result.decision is returned
    assert result.source == "legacy_coach_decision"
    assert calls[0] == ("clear", None)
    assert calls[1][1][0] == "J'ai pas eu le temps hier"
    assert calls[2][1]["coach_context"]["turn_primary_intent"] == "execution_report"
    assert calls[2][1]["tool_context"].pipeline == "conversation"


def test_provider_records_exception_without_raising() -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("provider down")

    provider = LegacyCoachDecisionProvider(decide_fn=broken, clear_fn=lambda: None)

    result = provider.decide(_request())

    assert result.decision is None
    assert result.error_type == "RuntimeError"
    assert "provider down" in str(result.error_message)
```

- [x] **Step 2: Run provider tests red**

Run:

```bash
./scripts/test-backend -q tests/test_coach_decision_provider.py
```

Expected:

```text
FAIL because fitmas.legacy.coach_decision_provider does not exist.
```

- [x] **Step 3: Implement provider adapter**

Create `backend/src/fitmas/legacy/coach_decision_provider.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from fitmas import llm as llm_runtime

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CoachDecisionRequest:
    user_text: str
    plan_summary: str
    timeline_summary: str | None = None
    execution_summary: str | None = None
    temporal_summary: str | None = None
    activity_claim_summary: str | None = None
    signal_summary: str | None = None
    conversation_history: list[dict] | None = None
    coach_context: dict | None = None
    remembered_facts: list[dict] | None = None
    time_context: dict | None = None
    tool_context: Any | None = None


@dataclass(frozen=True, slots=True)
class CoachDecisionResult:
    decision: Any | None
    source: str = "legacy_coach_decision"
    error_type: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.decision is not None and self.error_type is None


class LegacyCoachDecisionProvider:
    def __init__(
        self,
        *,
        decide_fn: Callable[..., Any] | None = None,
        clear_fn: Callable[[], None] | None = None,
    ) -> None:
        self._decide_fn = decide_fn or llm_runtime.decide
        self._clear_fn = clear_fn or llm_runtime.clear_last_decide_none

    def decide(self, request: CoachDecisionRequest) -> CoachDecisionResult:
        try:
            self._clear_fn()
            decision = self._decide_fn(
                request.user_text,
                request.plan_summary,
                timeline_summary=request.timeline_summary,
                execution_summary=request.execution_summary,
                temporal_summary=request.temporal_summary,
                activity_claim_summary=request.activity_claim_summary,
                signal_summary=request.signal_summary,
                conversation_history=request.conversation_history,
                coach_context=request.coach_context,
                remembered_facts=request.remembered_facts,
                time_context=request.time_context,
                tool_context=request.tool_context,
            )
            return CoachDecisionResult(decision=decision)
        except Exception as exc:
            logger.exception("legacy_coach_decision_provider_failed")
            return CoachDecisionResult(
                decision=None,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
```

- [x] **Step 4: Run provider tests green**

Run:

```bash
./scripts/test-backend -q tests/test_coach_decision_provider.py
```

Expected:

```text
2 passed.
```

## Task 3 - Create Conversation Decide Bridge

**Files:**

- Create: `backend/src/fitmas/legacy/conversation_decide_bridge.py`
- Create: `tests/test_conversation_decide_bridge.py`

- [x] **Step 1: Write bridge tests**

Create `tests/test_conversation_decide_bridge.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy.coach_decision_provider import CoachDecisionResult
from fitmas.legacy.conversation_decide_bridge import (
    build_legacy_coach_decision_request,
    run_legacy_coach_decision,
)


class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def decide(self, request):
        self.requests.append(request)
        return self.result


def test_build_request_carries_machine_context_only() -> None:
    request = build_legacy_coach_decision_request(
        user_text="déplace vendredi",
        user=SimpleNamespace(
            coach_name="FitMAS",
            coach_style="direct",
            coach_relationship="coach",
            coach_do="court",
            coach_dont="long",
            coach_soul="sobre",
            timezone="Europe/Paris",
        ),
        state=SimpleNamespace(
            timeline=("timeline-item",),
            conversation_history=[{"role": "user", "text": "avant"}],
            active_facts=[{"key": "availability:x"}],
            active_memory_rows=[],
            today_session=SimpleNamespace(id=12),
            scheduled_sessions=(),
            activities=(),
        ),
        turn_plan=SimpleNamespace(
            primary_intent="plan_mutation",
            secondary_intents=("availability_constraint",),
        ),
        coach_bundle=SimpleNamespace(
            planning_contract=SimpleNamespace(as_dict=lambda: {"planning": "contract"}),
            availability_state=SimpleNamespace(as_dict=lambda: {"availability": "state"}),
            week_mission=SimpleNamespace(as_dict=lambda: {"week": "mission"}),
            recent_reality=SimpleNamespace(as_dict=lambda: {"recent": "reality"}),
            latest_adaptation=None,
            week_summary="week",
            planning_context="planning",
            next_week="next",
            coach_reading="reading",
        ),
        conversation_context=SimpleNamespace(time_context={"today": "2026-05-15"}),
        timeline_summary="timeline summary",
        execution_summary="execution summary",
        temporal_summary="temporal summary",
        activity_claim_summary="claim summary",
        signal_summary="signal summary",
        selected_facts=[{"key": "selected"}],
        profile_summary="profile",
        coach_reading_digest_text="digest",
        unresolved_execution_followup_text=None,
        unresolved_execution_followup_session_id=None,
        unresolved_execution_followup_target_date=None,
        tool_context=SimpleNamespace(pipeline="conversation"),
    )

    assert request.user_text == "déplace vendredi"
    assert request.coach_context["turn_primary_intent"] == "plan_mutation"
    assert request.coach_context["turn_secondary_intents"] == ["availability_constraint"]
    assert request.coach_context["planning_contract"] == {"planning": "contract"}
    assert request.tool_context.pipeline == "conversation"


def test_run_legacy_coach_decision_records_trace() -> None:
    returned = SimpleNamespace(response_type="no_change", fitmas_message="ok")
    provider = FakeProvider(CoachDecisionResult(decision=returned))
    turn_context: dict[str, object] = {}

    result = run_legacy_coach_decision(
        provider=provider,
        request=build_legacy_coach_decision_request(
            user_text="ok",
            user=SimpleNamespace(
                coach_name=None,
                coach_style=None,
                coach_relationship=None,
                coach_do=None,
                coach_dont=None,
                coach_soul=None,
                timezone="Europe/Paris",
            ),
            state=SimpleNamespace(
                timeline=(),
                conversation_history=[],
                active_facts=[],
                active_memory_rows=[],
                today_session=None,
                scheduled_sessions=(),
                activities=(),
            ),
            turn_plan=SimpleNamespace(primary_intent="close_turn", secondary_intents=()),
            coach_bundle=SimpleNamespace(
                planning_contract=SimpleNamespace(as_dict=lambda: {}),
                availability_state=SimpleNamespace(as_dict=lambda: {}),
                week_mission=SimpleNamespace(as_dict=lambda: {}),
                recent_reality=SimpleNamespace(as_dict=lambda: {}),
                latest_adaptation=None,
                week_summary="",
                planning_context="",
                next_week="",
                coach_reading="",
            ),
            conversation_context=SimpleNamespace(time_context={}),
            timeline_summary="",
            execution_summary="",
            temporal_summary="",
            activity_claim_summary="",
            signal_summary="",
            selected_facts=[],
            profile_summary="",
            coach_reading_digest_text=None,
            unresolved_execution_followup_text=None,
            unresolved_execution_followup_session_id=None,
            unresolved_execution_followup_target_date=None,
            tool_context=None,
        ),
        turn_context=turn_context,
    )

    assert result is returned
    assert turn_context["legacy_decide"]["source"] == "legacy_coach_decision"
    assert turn_context["legacy_decide"]["ok"] is True
```

- [x] **Step 2: Run bridge tests red**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_decide_bridge.py
```

Expected:

```text
FAIL because fitmas.legacy.conversation_decide_bridge does not exist.
```

- [x] **Step 3: Implement bridge**

Create `backend/src/fitmas/legacy/conversation_decide_bridge.py`:

```python
from __future__ import annotations

from typing import Any

from fitmas.legacy.coach_decision_provider import (
    CoachDecisionRequest,
    CoachDecisionResult,
    LegacyCoachDecisionProvider,
)


def build_legacy_coach_decision_request(
    *,
    user_text: str,
    user,
    state,
    turn_plan,
    coach_bundle,
    conversation_context,
    timeline_summary: str,
    execution_summary: str,
    temporal_summary: str,
    activity_claim_summary: str,
    signal_summary: str,
    selected_facts: list[dict],
    profile_summary: str,
    coach_reading_digest_text: str | None,
    unresolved_execution_followup_text: str | None,
    unresolved_execution_followup_session_id: int | None,
    unresolved_execution_followup_target_date: str | None,
    tool_context: Any | None,
) -> CoachDecisionRequest:
    coach_context = {
        "coach_name": getattr(user, "coach_name", None),
        "coach_style": getattr(user, "coach_style", None),
        "coach_relationship": getattr(user, "coach_relationship", None),
        "coach_do": getattr(user, "coach_do", None),
        "coach_dont": getattr(user, "coach_dont", None),
        "coach_soul": getattr(user, "coach_soul", None),
        "timezone": getattr(user, "timezone", None),
        "today_session_id": getattr(getattr(state, "today_session", None), "id", None),
        "turn_primary_intent": getattr(turn_plan, "primary_intent", None),
        "turn_secondary_intents": list(getattr(turn_plan, "secondary_intents", ()) or ()),
        "turn_plan": _turn_plan_payload(turn_plan),
        "profile_summary": profile_summary,
        "selected_facts": selected_facts,
        "planning_contract": coach_bundle.planning_contract.as_dict(),
        "availability_state": coach_bundle.availability_state.as_dict(),
        "week_mission": coach_bundle.week_mission.as_dict(),
        "recent_reality": coach_bundle.recent_reality.as_dict(),
        "last_adaptation": coach_bundle.latest_adaptation.as_dict()
        if getattr(coach_bundle, "latest_adaptation", None) is not None
        else None,
        "week_context": {
            "summary": getattr(coach_bundle, "week_summary", ""),
            "planning": getattr(coach_bundle, "planning_context", ""),
            "next_week": getattr(coach_bundle, "next_week", ""),
            "coach_reading": getattr(coach_bundle, "coach_reading", ""),
        },
        "coach_reading_digest_text": coach_reading_digest_text,
        "unresolved_execution_followup": unresolved_execution_followup_text,
        "unresolved_execution_followup_session_id": unresolved_execution_followup_session_id,
        "unresolved_execution_followup_target_date": unresolved_execution_followup_target_date,
        "verify_execution_actions": True,
        "repair_memory_actions": True,
    }
    return CoachDecisionRequest(
        user_text=user_text,
        plan_summary="",
        timeline_summary=timeline_summary,
        execution_summary=execution_summary,
        temporal_summary=temporal_summary,
        activity_claim_summary=activity_claim_summary,
        signal_summary=signal_summary,
        conversation_history=getattr(state, "conversation_history", [])[:-1],
        coach_context=coach_context,
        remembered_facts=getattr(state, "active_facts", []),
        time_context=getattr(conversation_context, "time_context", None),
        tool_context=tool_context,
    )


def run_legacy_coach_decision(
    *,
    provider: LegacyCoachDecisionProvider,
    request: CoachDecisionRequest,
    turn_context: dict[str, object],
) -> Any | None:
    result = provider.decide(request)
    turn_context["legacy_decide"] = _result_trace(result)
    return result.decision


def _result_trace(result: CoachDecisionResult) -> dict[str, object]:
    return {
        "source": result.source,
        "ok": result.ok,
        "error_type": result.error_type,
        "decision_present": result.decision is not None,
    }


def _turn_plan_payload(turn_plan) -> dict | None:
    if turn_plan is None:
        return None
    if hasattr(turn_plan, "model_dump"):
        return dict(turn_plan.model_dump(mode="json"))
    payload: dict[str, object] = {}
    for name in (
        "primary_intent",
        "secondary_intents",
        "user_goal",
        "mutation_signal",
        "planning_action",
        "execution_claim",
        "availability_constraint",
        "temporal_references",
        "requires_truth_read",
        "truth_scope",
        "needs_clarification",
        "clarification_question",
        "confidence",
    ):
        if hasattr(turn_plan, name):
            value = getattr(turn_plan, name)
            payload[name] = list(value) if isinstance(value, tuple) else value
    return payload
```

- [x] **Step 4: Run bridge tests green**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_decide_bridge.py
```

Expected:

```text
2 passed.
```

## Task 4 - Wire Conversation Pipeline Through Decide Bridge

**Files:**

- Modify: `backend/src/fitmas/conversation_pipeline.py`
- Modify: `backend/src/fitmas/conversation_contract.py`
- Test: `tests/test_phase8l_decide_authority_architecture.py`
- Test: existing `tests/test_core_flows.py`

- [x] **Step 1: Update imports and dependency type**

In `backend/src/fitmas/conversation_pipeline.py`:

```python
from fitmas import repository as repo
from fitmas.legacy.coach_decision_provider import LegacyCoachDecisionProvider
from fitmas.legacy import conversation_decide_bridge
```

Remove:

```python
from fitmas import llm as llm_runtime, repository as repo
```

In `backend/src/fitmas/conversation_contract.py`, keep the `decide` callable for
existing tests and API injection, but rename its intent with a comment:

```python
@dataclass(frozen=True, slots=True)
class ConversationPipelineDependencies:
    decide: Callable[..., CoachDecision | MutationDecision | None]  # legacy provider callable
    extract_facts: Callable[[str, str, list[dict[str, Any]]], list[dict[str, Any]]]
    check_and_adapt_health_facts: Callable[..., Any]
    plan_turn: Callable[..., Any]
```

- [x] **Step 2: Replace the direct decide block**

Replace the direct `llm_runtime.clear_last_decide_none()` and
`dependencies.decide(...)` block in `conversation_pipeline.py` with:

```python
    decision_request = conversation_decide_bridge.build_legacy_coach_decision_request(
        user_text=payload.text,
        user=user,
        state=state,
        turn_plan=turn_plan,
        coach_bundle=coach_bundle,
        conversation_context=conversation_context,
        timeline_summary=api_messages.make_timeline_summary(state.timeline),
        execution_summary=execution_summary_for_prompt(conversation_context),
        temporal_summary=decision_temporal_summary,
        activity_claim_summary=claim_summary,
        signal_summary=decision_signal_summary,
        selected_facts=_selected_facts_for_prompt(conversation_context, state.active_facts),
        profile_summary=build_profile_summary(state.active_memory_rows),
        coach_reading_digest_text=_maybe_build_coach_reading_digest_text(
            db,
            user=user,
            today=conversation_context.temporal_resolution.local_date,
            recent_reality_window=coach_bundle.recent_reality,
            turn_plan=turn_plan,
        ),
        unresolved_execution_followup_text=unresolved_execution_followup_text,
        unresolved_execution_followup_session_id=unresolved_execution_followup_session_id,
        unresolved_execution_followup_target_date=unresolved_execution_followup_target_date,
        tool_context=ToolContext(
            pipeline="conversation",
            user_id=user.id,
            timezone_name=user.timezone,
            db=db,
            scheduled_sessions=state.scheduled_sessions,
            activities=state.activities,
            active_facts=state.active_facts,
        ),
    )
    decision = conversation_decide_bridge.run_legacy_coach_decision(
        provider=LegacyCoachDecisionProvider(decide_fn=dependencies.decide),
        request=decision_request,
        turn_context=turn_context,
    )
```

- [x] **Step 3: Run targeted architecture test**

Run:

```bash
./scripts/test-backend -q tests/test_phase8l_decide_authority_architecture.py
```

Expected:

```text
The direct decide assertion passes.
The direct fitmas_message assertion still fails until Task 5.
```

- [x] **Step 4: Run core dependency injection regression**

Run:

```bash
./scripts/test-backend -q tests/test_core_flows.py -k "slow_decide or decide\\(\\) must be called or mutation intent"
```

Expected:

```text
Selected tests pass or expose test names that need selector adjustment.
The injected `ConversationPipelineDependencies(decide=...)` fake is still called through the provider.
```

## Task 5 - Move CoachDecision Visible Reply Fallback Behind Bridge

**Files:**

- Create: `backend/src/fitmas/legacy/conversation_coach_decision_reply_bridge.py`
- Create: `tests/test_conversation_coach_decision_reply_bridge.py`
- Modify: `backend/src/fitmas/conversation_pipeline.py`

- [x] **Step 1: Write reply bridge tests**

Create `tests/test_conversation_coach_decision_reply_bridge.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from fitmas.legacy.conversation_coach_decision_reply_bridge import compose_coach_decision_reply


def test_reply_bridge_uses_confirmation_reason_before_message() -> None:
    outcome = compose_coach_decision_reply(
        db=None,
        user=SimpleNamespace(id=1),
        user_text="ok",
        decision=SimpleNamespace(
            response_type="requires_confirmation",
            confirmation_reason="Tu confirmes ?",
            fitmas_message="Brouillon",
        ),
        turn_context={"turn_plan": {"primary_intent": "plan_mutation"}},
        grounding=None,
        action_result={},
        compose_no_change_reply_for_turn_fn=None,
    )

    assert outcome.reply_text == "Tu confirmes ?"
    assert outcome.response_mode == "requires_confirmation"
    assert outcome.mutation_applied is False


def test_reply_bridge_routes_no_change_through_composer() -> None:
    calls = []

    def compose_no_change_reply_for_turn_fn(**kwargs):
        calls.append(kwargs)
        return "Reply composee", "no_change_composed"

    outcome = compose_coach_decision_reply(
        db=object(),
        user=SimpleNamespace(id=1),
        user_text="redonne le plan",
        decision=SimpleNamespace(
            response_type="no_change",
            confirmation_reason=None,
            fitmas_message="Brouillon legacy",
        ),
        turn_context={"turn_plan": {"primary_intent": "plan_lookup"}},
        grounding=SimpleNamespace(),
        action_result={"memory_applied": 0},
        compose_no_change_reply_for_turn_fn=compose_no_change_reply_for_turn_fn,
    )

    assert outcome.reply_text == "Reply composee"
    assert outcome.response_mode == "no_change_composed"
    assert calls[0]["original_reply"] == "Brouillon legacy"
```

- [x] **Step 2: Run reply bridge tests red**

Run:

```bash
./scripts/test-backend -q tests/test_conversation_coach_decision_reply_bridge.py
```

Expected:

```text
FAIL because the reply bridge does not exist.
```

- [x] **Step 3: Implement reply bridge**

Create `backend/src/fitmas/legacy/conversation_coach_decision_reply_bridge.py`:

```python
from __future__ import annotations

from typing import Any, Callable

from fitmas.conversation_contract import ConversationTurnOutcome
from fitmas.models import Extraction
from fitmas.legacy import conversation_readonly_reply_bridge


def compose_coach_decision_reply(
    *,
    db,
    user,
    user_text: str,
    decision: Any,
    turn_context: dict[str, object],
    grounding,
    action_result: dict,
    compose_no_change_reply_for_turn_fn: Callable[..., tuple[str, str | None]] | None,
) -> ConversationTurnOutcome:
    reply_text = str(getattr(decision, "confirmation_reason", None) or getattr(decision, "fitmas_message", ""))
    response_mode = str(getattr(decision, "response_type", "reply") or "reply")
    primary_intent = conversation_readonly_reply_bridge.turn_context_primary_intent(turn_context)
    should_compose = response_mode == "no_change" or (
        response_mode == "reply" and primary_intent == "execution_report"
    )
    if should_compose and compose_no_change_reply_for_turn_fn is not None:
        reply_text, composed_mode = compose_no_change_reply_for_turn_fn(
            db=db,
            user=user,
            user_text=user_text,
            original_reply=reply_text,
            turn_context=turn_context,
            grounding=grounding,
            action_result=action_result,
        )
        if composed_mode:
            response_mode = composed_mode
    return ConversationTurnOutcome(
        extraction=Extraction(confidence=0.85),
        reply_text=reply_text,
        response_mode=response_mode,
        decision=None,
        mutation_applied=False,
    )
```

- [x] **Step 4: Wire pipeline to reply bridge**

In `conversation_pipeline.py`, add import:

```python
from fitmas.legacy import conversation_coach_decision_reply_bridge
```

Replace the fallback block that reads `decision.confirmation_reason or decision.fitmas_message` with:

```python
    if outcome is None and is_coach_decision and decision is not None:
        outcome = conversation_coach_decision_reply_bridge.compose_coach_decision_reply(
            db=db,
            user=user,
            user_text=payload.text,
            decision=decision,
            turn_context=turn_context,
            grounding=grounding_packet,
            action_result=turn_context.get("coach_decision_action_result") or {},
            compose_no_change_reply_for_turn_fn=conversation_readonly_reply_bridge.compose_no_change_reply_for_turn,
        )
        decision = None
```

- [x] **Step 5: Run reply bridge and architecture tests green**

Run:

```bash
./scripts/test-backend -q \
  tests/test_conversation_coach_decision_reply_bridge.py \
  tests/test_phase8l_decide_authority_architecture.py
```

Expected:

```text
All selected tests pass.
```

## Task 6 - Preserve Canonical Precedence and Legacy Fallbacks

**Files:**

- Modify: `tests/test_conversation_command_bridge.py`
- Modify: `tests/test_conversation_pending_bridge.py`
- Modify: `tests/test_core_flows.py` only for targeted regression if needed

- [x] **Step 1: Run current precedence tests before changing logic**

Run:

```bash
./scripts/test-backend -q \
  tests/test_conversation_command_bridge.py \
  tests/test_conversation_pending_bridge.py \
  tests/test_conversation_understanding_bridge.py
```

Expected:

```text
All selected tests pass.
```

- [x] **Step 2: Add no-regression selector for 8K precedence**

If the existing files do not already cover these exact assertions after the
bridge move, add tests with these names:

```python
def test_8l_commands_still_prefer_understanding_when_present(monkeypatch):
    ...


def test_8l_pending_still_prefers_understanding_when_present(monkeypatch):
    ...


def test_8l_legacy_decide_still_fallbacks_when_understanding_empty(monkeypatch):
    ...
```

Use the existing helpers in `tests/test_conversation_command_bridge.py` and
`tests/test_conversation_pending_bridge.py`; do not introduce new fake
schemas.

- [x] **Step 3: Run precedence tests**

Run:

```bash
./scripts/test-backend -q \
  tests/test_conversation_command_bridge.py \
  tests/test_conversation_pending_bridge.py \
  tests/test_conversation_understanding_bridge.py
```

Expected:

```text
All selected tests pass.
```

## Task 7 - Add 8L Smoke Wrapper

**Files:**

- Create: `scripts/smoke-decision-runtime-decide-shrink`
- Modify: `tests/test_phase8l_decide_authority_architecture.py`

- [x] **Step 1: Add wrapper assertion to architecture test**

Extend `tests/test_phase8l_decide_authority_architecture.py`:

```python
def test_8l_smoke_wrapper_exists() -> None:
    script = ROOT / "scripts" / "smoke-decision-runtime-decide-shrink"

    assert script.exists()
    source = script.read_text(encoding="utf-8")
    assert "smoke-decision-runtime-canonical-defaults" in source
    assert "smoke-decision-runtime-canonical-planning" in source
    assert "test-backend -q" in source
```

- [x] **Step 2: Create wrapper**

Create `scripts/smoke-decision-runtime-decide-shrink`:

```zsh
#!/usr/bin/env zsh

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

./scripts/test-backend -q \
  tests/test_phase8l_decide_authority_architecture.py \
  tests/test_coach_decision_provider.py \
  tests/test_conversation_decide_bridge.py \
  tests/test_conversation_coach_decision_reply_bridge.py \
  tests/test_conversation_understanding_bridge.py \
  tests/test_conversation_command_bridge.py \
  tests/test_conversation_pending_bridge.py

./scripts/smoke-decision-runtime-canonical-defaults
./scripts/smoke-decision-runtime-canonical-planning
```

- [x] **Step 3: Make wrapper executable**

Run:

```bash
chmod +x scripts/smoke-decision-runtime-decide-shrink
```

- [x] **Step 4: Run wrapper architecture assertion**

Run:

```bash
./scripts/test-backend -q tests/test_phase8l_decide_authority_architecture.py
```

Expected:

```text
All selected tests pass.
```

## Task 8 - Documentation Updates

**Files:**

- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/README.md`

- [x] **Step 1: Update architecture doc**

Add after Phase 8K in `docs/DECISION-RUNTIME-REFACTOR.md`:

```markdown
Livres en Phase 8L :

- `decide()` est consomme via `legacy/coach_decision_provider.py` ;
- `conversation_pipeline.py` ne call plus `dependencies.decide` directement ;
- `conversation_pipeline.py` ne lit plus `decision.fitmas_message` directement ;
- `conversation_decide_bridge.py` construit la request legacy depuis les
  artefacts machine du tour ;
- `conversation_coach_decision_reply_bridge.py` porte la derniere fallback
  reply `CoachDecision` ;
- commands/pending canoniques restent default-on ;
- planning cutover canonique reste opt-in.
```

- [x] **Step 2: Update kill list**

In `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`, add Phase 8L status:

```markdown
### Phase 8L — Decide authority shrink

Resultat attendu :

- `CoachDecision` reste provider actif ;
- son autorite runtime est limitee aux bridges legacy ;
- `conversation_pipeline.py` ne parle plus directement son wire format ;
- `decision_legacy.py` reste a splitter en Phase 8M.
```

- [x] **Step 3: Update build order**

In `docs/BUILD-ORDER.md`, add:

```markdown
- Phase 8L livree localement :
  - retirer l'autorite directe de `decide()` dans `conversation_pipeline.py` ;
  - provider + bridges legacy livres ;
  - commands/pending canoniques default-on ;
  - planning cutover opt-in ;
  - prochaine phase probable : 8M split interne de `decision_legacy.py`.
```

- [x] **Step 4: Update README plan index**

In `docs/README.md`, add:

```markdown
- `superpowers/plans/2026-05-15-decision-runtime-phase-8l-decide-authority-shrink.md` — Phase 8L : shrink de l'autorite runtime de `decide()`.
```

## Task 9 - Verification Gate

Run:

```bash
./scripts/test-backend -q \
  tests/test_phase8l_decide_authority_architecture.py \
  tests/test_coach_decision_provider.py \
  tests/test_conversation_decide_bridge.py \
  tests/test_conversation_coach_decision_reply_bridge.py \
  tests/test_conversation_understanding_bridge.py \
  tests/test_conversation_command_bridge.py \
  tests/test_conversation_pending_bridge.py
```

Expected:

```text
all selected tests pass
```

Run:

```bash
./scripts/test-backend -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8b_cutover_architecture.py \
  tests/test_phase8c_legacy_kill_architecture.py \
  tests/test_phase8d_bridge_shrink_architecture.py \
  tests/test_phase8e_understanding_cutover_architecture.py \
  tests/test_phase8f_command_extraction_architecture.py \
  tests/test_phase8g_pending_resolution_architecture.py \
  tests/test_phase8h_pending_reply_architecture.py \
  tests/test_phase8i_canonical_flag_dogfood_architecture.py \
  tests/test_phase8j_canonical_planning_cutover_architecture.py \
  tests/test_phase8k_canonical_default_lanes_architecture.py \
  tests/test_phase8l_decide_authority_architecture.py
```

Expected:

```text
all selected architecture tests pass
```

Run:

```bash
./scripts/smoke-decision-runtime-decide-shrink
```

Expected:

```text
8L unit gates pass, 8K default smokes pass, 8J planning opt-in smokes pass
```

Run:

```bash
./scripts/test-backend -q
```

Expected:

```text
full backend suite passes
```

## Acceptance Criteria

8L is complete only if:

```text
1. conversation_pipeline.py does not call dependencies.decide directly.
2. conversation_pipeline.py does not import or alias fitmas.llm as llm_runtime.
3. conversation_pipeline.py does not read decision.fitmas_message directly.
4. Legacy decide calls pass through LegacyCoachDecisionProvider.
5. Provider failures return a result object instead of escaping.
6. Existing API injection of api_messages.decide still works.
7. Commands from Understanding remain default-on.
8. Pending from Understanding remains default-on.
9. Planning cutover remains default-off.
10. 8K and 8J smoke wrappers still pass.
11. Docs include fresh verification evidence.
```

## Implementation Result

Delivered locally on 2026-05-16.

Key results:

- `conversation_pipeline.py` no longer calls `dependencies.decide` directly.
- `conversation_pipeline.py` no longer imports or aliases `fitmas.llm` as
  `llm_runtime`.
- `conversation_pipeline.py` no longer reads `decision.fitmas_message`
  directly.
- `LegacyCoachDecisionProvider` owns the provider call and returns a result
  object.
- `conversation_decide_bridge.py` owns legacy request construction and
  `decide_none` context storage.
- `conversation_coach_decision_reply_bridge.py` owns the remaining
  `CoachDecision` reply fallback.
- Commands/pending canonical lanes remain default-on.
- Planning cutover remains opt-in.

Verification evidence:

```bash
./scripts/test-backend -q \
  tests/test_phase8l_decide_authority_architecture.py \
  tests/test_coach_decision_provider.py \
  tests/test_conversation_decide_bridge.py \
  tests/test_conversation_coach_decision_reply_bridge.py \
  tests/test_conversation_understanding_bridge.py \
  tests/test_conversation_command_bridge.py \
  tests/test_conversation_pending_bridge.py
```

Result:

```text
40 passed
```

```bash
./scripts/test-backend -q \
  tests/test_decision_runtime_architecture.py \
  tests/test_phase8a_legacy_audit.py \
  tests/test_phase8b_cutover_architecture.py \
  tests/test_phase8c_legacy_kill_architecture.py \
  tests/test_phase8d_bridge_shrink_architecture.py \
  tests/test_phase8e_understanding_cutover_architecture.py \
  tests/test_phase8f_command_extraction_architecture.py \
  tests/test_phase8g_pending_resolution_architecture.py \
  tests/test_phase8h_pending_reply_architecture.py \
  tests/test_phase8i_canonical_flag_dogfood_architecture.py \
  tests/test_phase8j_canonical_planning_cutover_architecture.py \
  tests/test_phase8k_canonical_default_lanes_architecture.py \
  tests/test_phase8l_decide_authority_architecture.py
```

Result:

```text
70 passed
```

```bash
./scripts/smoke-decision-runtime-decide-shrink
```

Result:

```text
RESULT: OK
```

```bash
./scripts/test-backend -q
```

Result:

```text
1234 passed, 11 skipped, 11 subtests passed
```

## After 8L

If 8L is green, the next phase should be 8M:

```text
Split decision_legacy.py internals into provider/prompt/parsing/action-compiler
modules without changing runtime behavior.
```

Recommended 8M boundaries:

```text
fitmas/llm/legacy_provider.py      provider call + retries
fitmas/llm/legacy_parser.py        CoachDecision parsing/normalization
fitmas/llm/legacy_action_compile.py memory/execution action compilers
fitmas/llm/legacy_prompt.py        prompt assembly adapters
```

Do not start 8M until 8L proves the runtime only sees `CoachDecision` through
legacy bridges.
